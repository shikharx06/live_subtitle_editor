"""Redis pub/sub fan-out: channel-per-project with a poll-based read loop."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Protocol

import redis.asyncio as redis

Handler = Callable[[dict[str, Any]], Awaitable[None]]


def channel(project_id: str) -> str:
    return f"project:{project_id}"


class PubSub(Protocol):
    async def subscribe(self, project_id: str, handler: Handler) -> None: ...
    async def unsubscribe(self, project_id: str) -> None: ...
    async def publish(self, project_id: str, message: dict[str, Any]) -> None: ...


class RedisPubSub:
    """Cross-instance broadcast over Redis pub/sub."""

    def __init__(self, client: redis.Redis):
        self._client = client
        self._pubsub = client.pubsub()
        self._handlers: dict[str, Handler] = {}
        self._reader: asyncio.Task | None = None

    async def start(self) -> None:
        await self._client.ping()
        self._reader = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        await self._pubsub.aclose()

    async def subscribe(self, project_id: str, handler: Handler) -> None:
        if project_id in self._handlers:
            return
        self._handlers[project_id] = handler
        await self._pubsub.subscribe(channel(project_id))

    async def unsubscribe(self, project_id: str) -> None:
        self._handlers.pop(project_id, None)
        await self._pubsub.unsubscribe(channel(project_id))

    async def publish(self, project_id: str, message: dict[str, Any]) -> None:
        await self._client.publish(channel(project_id), json.dumps(message))

    async def _read_loop(self) -> None:
        # Poll, not listen(): listen() dies on an empty subscription set at startup.
        while True:
            try:
                message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(0.1)
                continue
            if message is None or message.get("type") != "message":
                continue
            project_id = message["channel"].split(":", 1)[1]
            handler = self._handlers.get(project_id)
            if handler is None:
                continue
            try:
                await handler(json.loads(message["data"]))
            except Exception:
                pass
