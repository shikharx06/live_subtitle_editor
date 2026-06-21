"""Composition root: builds dependencies in lifespan, injects them, mounts routers."""

from __future__ import annotations

import os
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

_INDEX_HTML = os.path.join(os.path.dirname(__file__), "static", "index.html")


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
    with open(_INDEX_HTML, encoding="utf-8") as f:
        return HTMLResponse(f.read())


app.include_router(rest.router)
app.include_router(websocket.router)
