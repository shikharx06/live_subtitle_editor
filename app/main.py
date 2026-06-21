from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import db, ops
from .bus import Bus
from .config import get_settings
from .hub import Hub, Session
from .schema import bootstrap_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    pool = await db.create_pool(settings.database_url, settings.db_pool_min, settings.db_pool_max)
    await bootstrap_schema(pool)
    bus = Bus(settings.redis_url)
    await bus.start()
    app.state.pool = pool
    app.state.bus = bus
    app.state.hub = Hub(bus)
    app.state.instance_id = settings.instance_id
    try:
        yield
    finally:
        await bus.close()
        await pool.close()


app = FastAPI(title="Real-Time Collaborative Subtitles Editor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_INDEX_HTML = os.path.join(os.path.dirname(__file__), "static", "index.html")


class CreateProject(BaseModel):
    title: str | None = None


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(_INDEX_HTML, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/health")
async def health():
    try:
        async with app.state.pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok", "instance": app.state.instance_id}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/projects", status_code=201)
async def create_project(body: CreateProject):
    return await db.create_project(app.state.pool, body.title)


@app.get("/projects/{project_id}")
async def get_project(project_id: str):
    project = await db.get_project(app.state.pool, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    segments = await db.get_snapshot(app.state.pool, project_id)
    return {
        "id": project["id"],
        "title": project["title"],
        "current_seq": project["current_seq"],
        "snapshot_seq": project["snapshot_seq"],
        "segments": segments,
    }


@app.websocket("/projects/{project_id}/ws")
async def project_ws(ws: WebSocket, project_id: str):
    await ws.accept()
    pool = app.state.pool
    bus: Bus = app.state.bus
    hub: Hub = app.state.hub

    project = await db.get_project(pool, project_id)
    if project is None:
        await _send_error(ws, "UNKNOWN_PROJECT", "project not found")
        await ws.close()
        return

    try:
        hello = await ws.receive_json()
    except WebSocketDisconnect:
        return
    if hello.get("type") != "hello":
        await _send_error(ws, "PROTOCOL", "first message must be hello")
        await ws.close()
        return

    user_id = hello.get("user_id") or str(uuid.uuid4())
    last_seq = hello.get("last_seq")
    session = Session(ws, user_id)
    await hub.add(project_id, session)

    try:
        await _send_welcome(ws, bus, pool, project_id, user_id, last_seq)
        await _publish_presence(bus, project_id, user_id, hello.get("cursor"), "join")

        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "op":
                await _handle_op(ws, pool, bus, project_id, user_id, msg)
            elif mtype == "undo":
                await _handle_undo(ws, pool, bus, project_id, user_id, msg)
            elif mtype == "presence":
                await _publish_presence(bus, project_id, user_id, msg.get("cursor"), "update")
            elif mtype == "ping":
                await session.send({"type": "pong"})
            else:
                await _send_error(ws, "PROTOCOL", f"unknown message type {mtype!r}")
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(project_id, session)
        await bus.drop_presence(project_id, user_id)
        await _publish_presence(bus, project_id, user_id, None, "leave")


async def _send_welcome(ws, bus, pool, project_id, user_id, last_seq):
    project = await db.get_project(pool, project_id)
    current_seq = project["current_seq"]
    snapshot_seq = project["snapshot_seq"]
    peers = await bus.list_presence(project_id)

    if last_seq is None or last_seq < snapshot_seq:
        segments = await db.get_snapshot(pool, project_id)
        await ws.send_json(
            {
                "type": "welcome",
                "you": user_id,
                "current_seq": current_seq,
                "snapshot": {"segments": segments, "base_seq": snapshot_seq},
                "peers": peers,
            }
        )
        if last_seq is None and snapshot_seq < current_seq:
            tail = await db.get_ops_since(pool, project_id, snapshot_seq)
            if tail:
                await ws.send_json({"type": "sync", "ops": tail})
    else:
        await ws.send_json(
            {
                "type": "welcome",
                "you": user_id,
                "current_seq": current_seq,
                "base_seq": last_seq,
                "peers": peers,
            }
        )
        ops_since = await db.get_ops_since(pool, project_id, last_seq)
        if ops_since:
            await ws.send_json({"type": "sync", "ops": ops_since})


async def _handle_op(ws, pool, bus, project_id, user_id, msg):
    client_op_id = msg.get("client_op_id")
    op_type = msg.get("op_type") or msg.get("op")
    chunk_id = msg.get("chunk_id")
    if not client_op_id or not op_type:
        await _send_error(ws, "PROTOCOL", "op requires client_op_id and op_type")
        return

    try:
        payload, inverse, chunk_id = await _build_op(pool, project_id, op_type, chunk_id, msg)
    except ops.OpError as exc:
        await _send_error(ws, exc.code, exc.message)
        return

    result = await db.commit_op(
        pool, project_id, user_id, client_op_id, op_type, chunk_id, payload, inverse
    )
    seq = result["seq"]
    await ws.send_json({"type": "ack", "client_op_id": client_op_id, "seq": seq})

    if not result["duplicate"]:
        await bus.publish(
            project_id,
            {
                "type": "op",
                "seq": seq,
                "actor": user_id,
                "op_type": op_type,
                "chunk_id": chunk_id,
                "payload": payload,
                "ts": None,
            },
        )


async def _build_op(pool, project_id, op_type, chunk_id, msg):
    if op_type == "create":
        chunk_id = chunk_id or str(uuid.uuid4())
        positions = await db.neighbor_positions(pool, project_id)
        payload, inverse = ops.build_create(chunk_id, msg.get("fields", {}), positions)
        return payload, inverse, chunk_id
    if op_type == "update":
        current = await db.get_segment(pool, chunk_id)
        payload, inverse = ops.build_update(chunk_id, msg.get("fields", {}), current)
        return payload, inverse, chunk_id
    if op_type == "delete":
        current = await db.get_segment(pool, chunk_id)
        payload, inverse = ops.build_delete(chunk_id, current)
        return payload, inverse, chunk_id
    if op_type == "move":
        current = await db.get_segment(pool, chunk_id)
        positions = await db.neighbor_positions(pool, project_id)
        payload, inverse = ops.build_move(
            chunk_id, current, msg.get("before"), msg.get("after"), positions
        )
        return payload, inverse, chunk_id
    raise ops.OpError("BAD_OP", f"unknown op_type {op_type!r}")


async def _handle_undo(ws, pool, bus, project_id, user_id, msg):
    target = await db.last_undoable_op(pool, project_id, user_id)
    if target is None:
        await _send_error(ws, "NOTHING_TO_UNDO", "no undoable op")
        return
    try:
        forward = ops.build_undo(target, [])
    except ops.OpError as exc:
        await _send_error(ws, exc.code, exc.message)
        return

    client_op_id = msg.get("client_op_id") or str(uuid.uuid4())
    result = await db.commit_op(
        pool,
        project_id,
        user_id,
        client_op_id,
        forward["op_type"],
        forward["chunk_id"],
        forward["payload"],
        forward["inverse"],
    )
    seq = result["seq"]
    await ws.send_json({"type": "ack", "client_op_id": client_op_id, "seq": seq})
    if not result["duplicate"]:
        await bus.publish(
            project_id,
            {
                "type": "op",
                "seq": seq,
                "actor": user_id,
                "op_type": forward["op_type"],
                "chunk_id": forward["chunk_id"],
                "payload": forward["payload"],
                "ts": None,
            },
        )


async def _publish_presence(bus, project_id, user_id, cursor, status):
    if status != "leave":
        await bus.set_presence(project_id, user_id, {"user_id": user_id, "cursor": cursor})
    await bus.publish(
        project_id,
        {"type": "presence", "actor": user_id, "cursor": cursor, "status": status},
    )


async def _send_error(ws, code, message):
    try:
        await ws.send_json({"type": "error", "code": code, "message": message})
    except Exception:
        pass
