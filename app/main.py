"""Composition root: builds dependencies in lifespan, injects them, mounts routers."""

from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .api import rest, websocket
from .config import get_settings
from .domain.operations import OperationFactory
from .persistence.database import create_pool
from .persistence.schema import bootstrap_schema
from .realtime.presence import PresenceStore
from .realtime.pubsub import RedisPubSub
from .realtime.sessions import ConnectionManager
from .services.collaboration import CollaborationService

_API_NOTICE = """<!doctype html>
<meta charset="utf-8">
<title>Subtitles API</title>
<style>
  body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f7f5ef;
    color:#1c1b18;font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  .card{max-width:34rem;padding:2.5rem;border:1px solid #e9e5dc;border-radius:16px;background:#fff;
    box-shadow:0 1px 2px rgba(28,27,24,.04),0 24px 48px -32px rgba(28,27,24,.25)}
  h1{margin:0 0 .25rem;font-size:1.4rem;letter-spacing:-.01em}
  p{margin:.4rem 0;color:#6e6a61}
  code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;background:#f2efe7;
    padding:.1rem .4rem;border-radius:6px;color:#0f5e4e}
  .dot{display:inline-block;width:.5rem;height:.5rem;border-radius:50%;background:#0f7a66;margin-right:.5rem}
  ul{margin:1rem 0 0;padding-left:1.1rem}
</style>
<div class="card">
  <h1><span class="dot"></span>Real-Time Collaborative Subtitles &mdash; API</h1>
  <p>This host serves the REST + WebSocket backend. The web client is the Next.js app
     (run <code>cd web &amp;&amp; npm run dev</code>, then open <code>http://localhost:3000</code>).</p>
  <ul>
    <li><code>POST /projects</code> &middot; <code>GET /projects/{id}</code> &middot; <code>GET /health</code></li>
    <li><code>WS /projects/{id}/ws</code></li>
  </ul>
</div>
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    pool = await create_pool(settings.database_url, settings.db_pool_min, settings.db_pool_max)
    await bootstrap_schema(pool)

    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    pubsub = RedisPubSub(redis_client)
    await pubsub.start()

    app.state.pool = pool
    app.state.instance_id = settings.instance_id
    app.state.pubsub = pubsub
    app.state.presence = PresenceStore(redis_client)
    app.state.connections = ConnectionManager(pubsub)
    app.state.collaboration = CollaborationService(pool, OperationFactory())
    try:
        yield
    finally:
        await pubsub.close()
        await redis_client.aclose()
        await pool.close()


app = FastAPI(title="Real-Time Collaborative Subtitles Editor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(_API_NOTICE)


app.include_router(rest.router)
app.include_router(websocket.router)
