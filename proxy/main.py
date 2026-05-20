import json
import os
import time
import uuid
import sqlite3
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
DB_PATH = os.getenv("DB_PATH", "/data/keys.db")
AUTOCOMPLETE_MODEL = os.getenv("AUTOCOMPLETE_MODEL")
if not AUTOCOMPLETE_MODEL:
    raise RuntimeError("AUTOCOMPLETE_MODEL environment variable is not set")

app = FastAPI(title="Ollama Access Proxy")


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.on_event("startup")
def startup():
    conn = get_db()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key       TEXT PRIMARY KEY,
            name      TEXT NOT NULL DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            active    INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            model             TEXT NOT NULL,
            prompt_tokens     INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _record_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO token_usage (model, prompt_tokens, completion_tokens) VALUES (?, ?, ?)",
            (model, prompt_tokens, completion_tokens),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# --- dependency helpers ---

def require_admin(request: Request):
    key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")


def require_api_key(request: Request):
    key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    conn = get_db()
    row = conn.execute(
        "SELECT key FROM api_keys WHERE key = ? AND active = 1", (key,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    return key


# --- admin routes ---

@app.post("/admin/keys", dependencies=[Depends(require_admin)])
def create_key(name: str = ""):
    key = f"ollama-{uuid.uuid4().hex}"
    conn = get_db()
    conn.execute("INSERT INTO api_keys (key, name) VALUES (?, ?)", (key, name))
    conn.commit()
    conn.close()
    return {"key": key, "name": name}


@app.get("/admin/keys", dependencies=[Depends(require_admin)])
def list_keys():
    conn = get_db()
    rows = conn.execute(
        "SELECT key, name, created_at, active FROM api_keys ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.delete("/admin/keys/{key}", dependencies=[Depends(require_admin)])
def revoke_key(key: str):
    conn = get_db()
    conn.execute("UPDATE api_keys SET active = 0 WHERE key = ?", (key,))
    conn.commit()
    conn.close()
    return {"revoked": key}


# --- autocomplete ---

class CompletionRequest(BaseModel):
    prompt: str
    suffix: str | None = None
    max_tokens: int = 128
    temperature: float = 0.2
    stream: bool = False
    stop: list[str] | str | None = None


@app.post("/v1/completions", dependencies=[Depends(require_api_key)])
async def completions(req: CompletionRequest):
    stop = [req.stop] if isinstance(req.stop, str) else (req.stop or [])
    ollama_body = {
        "model": AUTOCOMPLETE_MODEL,
        "prompt": req.prompt,
        "stream": req.stream,
        "options": {
            "num_predict": req.max_tokens,
            "temperature": req.temperature,
            **({"stop": stop} if stop else {}),
        },
        **({"suffix": req.suffix} if req.suffix is not None else {}),
    }

    completion_id = f"cmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    client = httpx.AsyncClient(timeout=None)

    if req.stream:
        upstream = await client.send(
            client.build_request("POST", f"{OLLAMA_URL}/api/generate", json=ollama_body),
            stream=True,
        )

        async def stream_sse():
            try:
                async for line in upstream.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    text = chunk.get("response", "")
                    done = chunk.get("done", False)
                    payload = {
                        "id": completion_id,
                        "object": "text_completion",
                        "created": created,
                        "model": AUTOCOMPLETE_MODEL,
                        "choices": [{"text": text, "index": 0, "finish_reason": "stop" if done else None}],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    if done:
                        _record_usage(
                            AUTOCOMPLETE_MODEL,
                            chunk.get("prompt_eval_count", 0),
                            chunk.get("eval_count", 0),
                        )
                        yield "data: [DONE]\n\n"
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(stream_sse(), media_type="text/event-stream")

    resp = await client.post(f"{OLLAMA_URL}/api/generate", json=ollama_body)
    await client.aclose()
    data = resp.json()
    _record_usage(
        AUTOCOMPLETE_MODEL,
        data.get("prompt_eval_count", 0),
        data.get("eval_count", 0),
    )
    return {
        "id": completion_id,
        "object": "text_completion",
        "created": created,
        "model": AUTOCOMPLETE_MODEL,
        "choices": [{"text": data.get("response", ""), "index": 0, "finish_reason": "stop"}],
    }


# --- proxy ---

SKIP_HEADERS = {"host", "authorization", "transfer-encoding"}
TRACKED_PATHS = {"api/generate", "api/chat"}


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy(path: str, request: Request, _: str = Depends(require_api_key)):
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in SKIP_HEADERS}

    tracked_model: str | None = None
    if path in TRACKED_PATHS:
        try:
            tracked_model = json.loads(body).get("model")
        except Exception:
            pass

    client = httpx.AsyncClient(timeout=None)
    upstream = await client.send(
        client.build_request(
            method=request.method,
            url=f"{OLLAMA_URL}/{path}",
            headers=headers,
            content=body,
            params=request.query_params,
        ),
        stream=True,
    )

    resp_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in {"transfer-encoding", "content-encoding"}
    }

    async def stream():
        last_chunk = b""
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
                if chunk.strip():
                    last_chunk = chunk
        finally:
            if tracked_model and last_chunk:
                for line in reversed(last_chunk.strip().split(b"\n")):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("done"):
                            _record_usage(
                                tracked_model,
                                obj.get("prompt_eval_count", 0),
                                obj.get("eval_count", 0),
                            )
                        break
                    except Exception:
                        continue
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        headers=resp_headers,
        media_type=upstream.headers.get("content-type"),
    )
