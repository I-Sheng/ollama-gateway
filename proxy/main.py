import os
import uuid
import sqlite3
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
DB_PATH = os.getenv("DB_PATH", "/data/keys.db")

app = FastAPI(title="Ollama Access Proxy")


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.on_event("startup")
def startup():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            key       TEXT PRIMARY KEY,
            name      TEXT NOT NULL DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            active    INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()


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


# --- proxy ---

SKIP_HEADERS = {"host", "authorization", "transfer-encoding"}


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy(path: str, request: Request, _: str = Depends(require_api_key)):
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in SKIP_HEADERS}

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
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        headers=resp_headers,
        media_type=upstream.headers.get("content-type"),
    )
