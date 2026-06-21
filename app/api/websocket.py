"""WebSocket endpoint and the per-connection editor protocol (§5.5)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..domain.operations import OpError
from ..realtime.presence import PresenceStore
from ..realtime.pubsub import PubSub
from ..realtime.sessions import ConnectionManager, Session
from ..services.collaboration import CollaborationService

router = APIRouter()


@router.websocket("/projects/{project_id}/ws")
async def project_ws(ws: WebSocket, project_id: str):
    await ws.accept()
    state = ws.app.state
    conn = EditorConnection(
        ws=ws,
        project_id=project_id,
        service=state.collaboration,
        connections=state.connections,
        pubsub=state.pubsub,
        presence=state.presence,
    )
    await conn.run()


class EditorConnection:
    """One client connection; dispatches incoming messages by type."""

    def __init__(
        self,
        ws: WebSocket,
        project_id: str,
        service: CollaborationService,
        connections: ConnectionManager,
        pubsub: PubSub,
        presence: PresenceStore,
    ):
        self._ws = ws
        self._project_id = project_id
        self._service = service
        self._connections = connections
        self._pubsub = pubsub
        self._presence = presence
        self._user_id = ""
        self._session: Session | None = None
        self._dispatch = {
            "op": self._handle_op,
            "undo": self._handle_undo,
            "presence": self._handle_presence,
            "ping": self._handle_ping,
        }

    async def run(self) -> None:
        project = await self._service.get_project(self._project_id)
        if project is None:
            await self._send_error("UNKNOWN_PROJECT", "project not found")
            await self._ws.close()
            return

        try:
            hello = await self._ws.receive_json()
        except WebSocketDisconnect:
            return
        if hello.get("type") != "hello":
            await self._send_error("PROTOCOL", "first message must be hello")
            await self._ws.close()
            return

        self._user_id = hello.get("user_id") or str(uuid.uuid4())
        last_seq = hello.get("last_seq")
        self._session = Session(self._ws, self._user_id)
        await self._connections.add(self._project_id, self._session)

        try:
            await self._send_welcome(last_seq)
            await self._publish_presence(hello.get("cursor"), "join")
            while True:
                msg = await self._ws.receive_json()
                handler = self._dispatch.get(msg.get("type"))
                if handler is None:
                    await self._send_error("PROTOCOL", f"unknown message type {msg.get('type')!r}")
                    continue
                await handler(msg)
        except WebSocketDisconnect:
            pass
        finally:
            await self._connections.remove(self._project_id, self._session)
            await self._presence.drop(self._project_id, self._user_id)
            await self._publish_presence(None, "leave")

    async def _send_welcome(self, last_seq: int | None) -> None:
        project = await self._service.get_project(self._project_id)
        current_seq = project.current_seq
        snapshot_seq = project.snapshot_seq
        peers = await self._presence.list(self._project_id)

        if last_seq is None or last_seq < snapshot_seq:
            segments = await self._service.snapshot(self._project_id)
            await self._ws.send_json(
                {
                    "type": "welcome",
                    "you": self._user_id,
                    "current_seq": current_seq,
                    "snapshot": {
                        "segments": [s.to_public() for s in segments],
                        "base_seq": snapshot_seq,
                    },
                    "peers": peers,
                }
            )
            if last_seq is None and snapshot_seq < current_seq:
                tail = await self._service.ops_since(self._project_id, snapshot_seq)
                if tail:
                    await self._ws.send_json({"type": "sync", "ops": [o.to_wire() for o in tail]})
        else:
            await self._ws.send_json(
                {
                    "type": "welcome",
                    "you": self._user_id,
                    "current_seq": current_seq,
                    "base_seq": last_seq,
                    "peers": peers,
                }
            )
            ops_since = await self._service.ops_since(self._project_id, last_seq)
            if ops_since:
                await self._ws.send_json({"type": "sync", "ops": [o.to_wire() for o in ops_since]})

    async def _handle_op(self, msg: dict[str, Any]) -> None:
        client_op_id = msg.get("client_op_id")
        op_type = msg.get("op_type") or msg.get("op")
        chunk_id = msg.get("chunk_id")
        if not client_op_id or not op_type:
            await self._send_error("PROTOCOL", "op requires client_op_id and op_type")
            return

        try:
            op = await self._service.build_from_client(self._project_id, op_type, chunk_id, msg)
        except OpError as exc:
            await self._send_error(exc.code, exc.message)
            return

        result = await self._service.commit(self._project_id, self._user_id, client_op_id, op)
        await self._ws.send_json({"type": "ack", "client_op_id": client_op_id, "seq": result.seq})
        if not result.duplicate:
            await self._broadcast_op(result.seq, op)

    async def _handle_undo(self, msg: dict[str, Any]) -> None:
        try:
            forward = await self._service.build_undo(self._project_id, self._user_id)
        except OpError as exc:
            await self._send_error(exc.code, exc.message)
            return
        if forward is None:
            await self._send_error("NOTHING_TO_UNDO", "no undoable op")
            return

        client_op_id = msg.get("client_op_id") or str(uuid.uuid4())
        result = await self._service.commit(self._project_id, self._user_id, client_op_id, forward)
        await self._ws.send_json({"type": "ack", "client_op_id": client_op_id, "seq": result.seq})
        if not result.duplicate:
            await self._broadcast_op(result.seq, forward)

    async def _handle_presence(self, msg: dict[str, Any]) -> None:
        await self._publish_presence(msg.get("cursor"), "update")

    async def _handle_ping(self, msg: dict[str, Any]) -> None:
        await self._session.send({"type": "pong"})

    async def _broadcast_op(self, seq: int, op) -> None:
        await self._pubsub.publish(
            self._project_id,
            {
                "type": "op",
                "seq": seq,
                "actor": self._user_id,
                "op_type": op.op_type,
                "chunk_id": op.chunk_id,
                "payload": op.payload,
                "ts": None,
            },
        )

    async def _publish_presence(self, cursor: Any, status: str) -> None:
        if status != "leave":
            await self._presence.set(
                self._project_id, self._user_id, {"user_id": self._user_id, "cursor": cursor}
            )
        await self._pubsub.publish(
            self._project_id,
            {"type": "presence", "actor": self._user_id, "cursor": cursor, "status": status},
        )

    async def _send_error(self, code: str, message: str) -> None:
        try:
            await self._ws.send_json({"type": "error", "code": code, "message": message})
        except Exception:
            pass
