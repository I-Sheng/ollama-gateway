import os
import sqlite3
import uuid
import httpx
import psutil
from fastapi import FastAPI, Request, HTTPException, Response, Depends
from fastapi.responses import HTMLResponse

try:
    from pynvml import (
        nvmlInit, nvmlShutdown, nvmlDeviceGetCount, nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetUtilizationRates, nvmlDeviceGetMemoryInfo,
        nvmlDeviceGetTemperature, NVML_TEMPERATURE_GPU,
        nvmlDeviceGetPowerUsage, nvmlDeviceGetName, NVMLError,
    )
    nvmlInit()
    NVML_AVAILABLE = True
except Exception:
    NVML_AVAILABLE = False

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DB_PATH = os.getenv("DB_PATH", "/data/keys.db")

app = FastAPI(title="OE Dashboard")

sessions: set[str] = set()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_tables():
    try:
        conn = get_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                model             TEXT NOT NULL,
                prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                tokens_per_sec    REAL,
                created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute("ALTER TABLE token_usage ADD COLUMN tokens_per_sec REAL")
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception:
        pass


@app.on_event("startup")
def startup():
    ensure_tables()


# --- auth ---

def check_session(request: Request):
    if request.cookies.get("session", "") not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")


@app.post("/auth/login")
async def login(request: Request, response: Response):
    data = await request.json()
    if not DASHBOARD_PASSWORD or data.get("password") != DASHBOARD_PASSWORD:
        raise HTTPException(status_code=401, detail="Wrong password")
    token = uuid.uuid4().hex
    sessions.add(token)
    response.set_cookie("session", token, httponly=True, samesite="strict")
    return {"ok": True}


@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    sessions.discard(request.cookies.get("session", ""))
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/auth/check")
async def auth_check(request: Request):
    return {"authenticated": request.cookies.get("session", "") in sessions}


# --- GPU ---

@app.get("/api/gpu", dependencies=[Depends(check_session)])
def gpu_stats():
    if not NVML_AVAILABLE:
        return {"error": "NVML not available", "gpus": []}
    try:
        count = nvmlDeviceGetCount()
        gpus = []
        for i in range(count):
            handle = nvmlDeviceGetHandleByIndex(i)
            util = nvmlDeviceGetUtilizationRates(handle)
            mem = nvmlDeviceGetMemoryInfo(handle)
            temp = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
            try:
                power_w = nvmlDeviceGetPowerUsage(handle) / 1000.0
            except NVMLError:
                power_w = None
            gpus.append({
                "index": i,
                "name": nvmlDeviceGetName(handle),
                "utilization": util.gpu,
                "memory_used": mem.used,
                "memory_total": mem.total,
                "temperature": temp,
                "power_watts": power_w,
            })
        return {"gpus": gpus}
    except NVMLError as e:
        return {"error": str(e), "gpus": []}


# --- System memory ---

@app.get("/api/memory", dependencies=[Depends(check_session)])
def memory_stats():
    mem = psutil.virtual_memory()
    return {"used": mem.used, "total": mem.total, "percent": mem.percent}


# --- Token usage ---

@app.get("/api/usage", dependencies=[Depends(check_session)])
def usage_stats():
    try:
        conn = get_db()
        daily = conn.execute("""
            SELECT DATE(created_at) AS date, model,
                   COUNT(*) AS requests,
                   SUM(prompt_tokens) AS prompt_tokens,
                   SUM(completion_tokens) AS completion_tokens
            FROM token_usage
            GROUP BY DATE(created_at), model
            ORDER BY date DESC
            LIMIT 200
        """).fetchall()
        totals = conn.execute("""
            SELECT model,
                   COUNT(*) AS requests,
                   SUM(prompt_tokens) AS prompt_tokens,
                   SUM(completion_tokens) AS completion_tokens
            FROM token_usage
            GROUP BY model
            ORDER BY requests DESC
        """).fetchall()
        conn.close()
        return {"daily": [dict(r) for r in daily], "totals": [dict(r) for r in totals]}
    except Exception as e:
        return {"daily": [], "totals": [], "error": str(e)}


# --- Models ---

@app.get("/api/models", dependencies=[Depends(check_session)])
async def list_models():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{OLLAMA_URL}/api/tags")
        return resp.json()


@app.get("/api/models/running", dependencies=[Depends(check_session)])
async def running_models():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{OLLAMA_URL}/api/ps")
        return resp.json()


@app.post("/api/models/pull", dependencies=[Depends(check_session)])
async def pull_model(request: Request):
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Model name required")
    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/pull", json={"name": name})
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Ollama pull failed")
    return {"ok": True}


@app.delete("/api/models/{name:path}", dependencies=[Depends(check_session)])
async def delete_model(name: str):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.request("DELETE", f"{OLLAMA_URL}/api/delete", json={"name": name})
    return {"ok": True}


@app.get("/api/models/show/{name:path}", dependencies=[Depends(check_session)])
async def show_model(name: str):
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/show", json={"name": name})
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Ollama show failed")
        data = resp.json()
    params: dict[str, str] = {}
    for line in data.get("parameters", "").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            params[parts[0]] = parts[1]
    return {
        "name": name,
        "num_ctx": params.get("num_ctx"),
        "num_gpu": params.get("num_gpu"),
        "temperature": params.get("temperature"),
        "details": data.get("details", {}),
    }


@app.get("/api/speed", dependencies=[Depends(check_session)])
def speed_stats():
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT model, tokens_per_sec, created_at
            FROM token_usage
            WHERE tokens_per_sec IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 50
        """).fetchall()
        conn.close()
        return {"recent": [dict(r) for r in rows]}
    except Exception as e:
        return {"recent": [], "error": str(e)}


@app.post("/api/models/configure", dependencies=[Depends(check_session)])
async def configure_model(request: Request):
    """Derive a new model with custom parameters via Modelfile."""
    data = await request.json()
    base = data.get("model", "").strip()
    if not base:
        raise HTTPException(status_code=400, detail="Base model required")

    lines = [f"FROM {base}"]
    if data.get("num_ctx"):
        lines.append(f"PARAMETER num_ctx {int(data['num_ctx'])}")
    if data.get("num_gpu") is not None and data["num_gpu"] != "":
        lines.append(f"PARAMETER num_gpu {int(data['num_gpu'])}")
    if data.get("temperature") is not None and data["temperature"] != "":
        lines.append(f"PARAMETER temperature {float(data['temperature'])}")

    target = data.get("target_name") or (base.split(":")[0] + "-custom")
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/create", json={
            "name": target,
            "modelfile": "\n".join(lines),
        })
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Ollama create failed")
    return {"ok": True, "name": target}


# --- UI ---

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("/app/index.html") as f:
        return f.read()
