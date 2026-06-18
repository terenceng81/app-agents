#!/usr/bin/env python3
"""
app-builder-api.py — FastAPI server for App Builder UI
Wraps build-app.sh as HTTP endpoints. Run via launchd on port 8788.
Expose publicly with: cloudflared tunnel --url http://localhost:8788
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import re

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── Paths ─────────────────────────────────────────────────────────────────────

HERMES_DIR   = Path.home() / ".hermes"
SCRIPTS_DIR  = HERMES_DIR / "scripts"
REGISTRY     = HERMES_DIR / "app-builder" / "apps.json"
BUILD_SCRIPT = SCRIPTS_DIR / "build-app.sh"

# ── Env ───────────────────────────────────────────────────────────────────────

def load_env() -> dict:
    env = {}
    p = HERMES_DIR / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV     = load_env()
API_KEY = ENV.get("APP_BUILDER_API_KEY", "")
PORT    = int(ENV.get("APP_BUILDER_API_PORT", "8788"))

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="App Builder API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth ──────────────────────────────────────────────────────────────────────

def require_key(request: Request):
    if API_KEY and request.headers.get("X-API-Key", "") != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

# ── Build state ───────────────────────────────────────────────────────────────

build_lock = asyncio.Lock()

state: dict = {
    "running":    False,
    "repo_name":  None,
    "started_at": None,
    "log":        [],   # all lines since last build
}

# ── Models ────────────────────────────────────────────────────────────────────

class CreateReq(BaseModel):
    tg_user_id:  str
    tg_username: str = "ui"
    description: str
    provider:    str = "claude-code"

class UpdateReq(BaseModel):
    tg_user_id:     str
    repo_name:      str
    update_request: str
    provider:       str = "claude-code"

# ── Helpers ───────────────────────────────────────────────────────────────────

def registry_data() -> dict:
    try:
        return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    except Exception:
        return {}

async def _run(cmd: list[str]):
    state["running"]    = True
    state["started_at"] = time.time()
    state["log"]        = []
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, **ENV},
        )
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            state["log"].append(line)
        await proc.wait()
        state["log"].append(f"[exit {proc.returncode}]")
    except Exception as e:
        state["log"].append(f"[ERROR] {e}")
    finally:
        state["running"] = False

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "running": state["running"]}


@app.get("/api/apps")
def list_apps(request: Request):
    require_key(request)
    data = registry_data()
    # Enrich with Cloudflare custom domain derived from repo name
    cf_base = ENV.get("CUSTOM_DOMAIN_BASE", "nhkclouds.com")
    result = {}
    for repo, info in data.items():
        slug = re.sub(r'^app-tg\d+-', '', repo)
        result[repo] = {
            **info,
            "repo_name":    repo,
            "custom_url":   f"https://{slug}.{cf_base}",
            "vercel_url":   f"https://{repo}.vercel.app",
            "github_url":   f"https://github.com/{ENV.get('GITHUB_OWNER','terenceng81')}/{repo}",
        }
    return result


@app.get("/api/build/status")
def build_status():
    return {
        "running":    state["running"],
        "repo_name":  state["repo_name"],
        "started_at": state["started_at"],
        "log":        state["log"][-100:],
    }


@app.get("/api/log/stream")
async def log_stream():
    """Server-Sent Events stream of live build output."""
    async def generate():
        last = 0
        while True:
            lines = state["log"]
            if len(lines) > last:
                for line in lines[last:]:
                    yield f"data: {json.dumps({'line': line})}\n\n"
                last = len(lines)
            if not state["running"]:
                yield f"data: {json.dumps({'done': True, 'log': state['log']})}\n\n"
                break
            await asyncio.sleep(0.3)
    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/build")
async def create_app(req: CreateReq, request: Request, bg: BackgroundTasks):
    require_key(request)
    if state["running"]:
        raise HTTPException(status_code=409,
                            detail=f"Build already running: {state['repo_name']}. Please wait.")
    state["repo_name"] = f"app-tg{req.tg_user_id}-pending"
    cmd = ["bash", str(BUILD_SCRIPT), "create",
           req.tg_user_id, req.tg_username, req.description, req.provider]
    bg.add_task(_run, cmd)
    return {"status": "started", "stream": "/api/log/stream"}


@app.post("/api/update")
async def update_app(req: UpdateReq, request: Request, bg: BackgroundTasks):
    require_key(request)
    if state["running"]:
        raise HTTPException(status_code=409,
                            detail=f"Build already running: {state['repo_name']}. Please wait.")
    state["repo_name"] = req.repo_name
    cmd = ["bash", str(BUILD_SCRIPT), "update",
           req.tg_user_id, req.repo_name, req.update_request, req.provider]
    bg.add_task(_run, cmd)
    return {"status": "started", "stream": "/api/log/stream"}


@app.delete("/api/app/{repo_name}")
async def delete_app(repo_name: str, request: Request):
    require_key(request)
    if state["running"]:
        raise HTTPException(status_code=409,
                            detail=f"Build already running: {state['repo_name']}. Please wait.")
    proc = await asyncio.create_subprocess_exec(
        "bash", str(BUILD_SCRIPT), "delete", repo_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **ENV},
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace")
    return {
        "status": "deleted" if proc.returncode == 0 else "error",
        "output": output,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app-builder-api:app", host="0.0.0.0", port=PORT, reload=False)
