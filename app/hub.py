from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket

from .bus import Bus


class Session:
    def __init__(self, ws: WebSocket, user_id: str):
        self.ws = ws
        self.user_id = user_id

    async def send(self, message: dict[str, Any]) -> None:
        await self.ws.send_text(json.dumps(message))


class Hub:
    """Per-instance registry of local WS sessions, subscribed to Redis per active project."""

    def __init__(self, bus: Bus):
        self._bus = bus
        self._sessions: dict[str, set[Session]] = {}
        self._lock = asyncio.Lock()

    async def add(self, project_id: str, session: Session) -> None:
        async with self._lock:
            first = project_id not in self._sessions
            self._sessions.setdefault(project_id, set()).add(session)
            if first:
                await self._bus.subscribe(project_id, self._make_relay(project_id))

    async def remove(self, project_id: str, session: Session) -> None:
        async with self._lock:
            peers = self._sessions.get(project_id)
            if not peers:
                return
            peers.discard(session)
            if not peers:
                del self._sessions[project_id]
                await self._bus.unsubscribe(project_id)

    def _make_relay(self, project_id: str):
        async def relay(message: dict[str, Any]) -> None:
            await self._deliver_local(project_id, message)

        return relay

    async def _deliver_local(self, project_id: str, message: dict[str, Any]) -> None:
        for session in list(self._sessions.get(project_id, ())):
            try:
                await session.send(message)
            except Exception:
                await self.remove(project_id, session)
