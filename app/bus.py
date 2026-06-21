from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Coroutine

import redis.asyncio as redis


def channel(project_id: str) -> str:
    return f"project:{project_id}"


def presence_key(project_id: str) -> str:
    return f"presence:{project_id}"


PRESENCE_TTL_SECONDS = 30


class Bus:
    """Redis pub/sub fan-out plus the ephemeral presence hash (§5.8)."""

    def __init__(self, url: str):
        self._client = redis.from_url(url, decode_responses=True)
        self._pubsub = self._client.pubsub()
        self._handlers: dict[str, Callable[[dict[str, Any]], Coroutine]] = {}
        self._reader: asyncio.Task | None = None

    async def start(self) -> None:
        await self._client.ping()
        self._reader = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        await self._pubsub.aclose()
        await self._client.aclose()

    async def subscribe(
        self, project_id: str, handler: Callable[[dict[str, Any]], Coroutine]
    ) -> None:
        if project_id in self._handlers:
            return
        self._handlers[project_id] = handler
        await self._pubsub.subscribe(channel(project_id))

    async def unsubscribe(self, project_id: str) -> None:
        self._handlers.pop(project_id, None)
        await self._pubsub.unsubscribe(channel(project_id))

    async def publish(self, project_id: str, message: dict[str, Any]) -> None:
        await self._client.publish(channel(project_id), json.dumps(message))

    async def set_presence(self, project_id: str, user_id: str, value: dict[str, Any]) -> None:
        key = presence_key(project_id)
        await self._client.hset(key, user_id, json.dumps(value))
        await self._client.expire(key, PRESENCE_TTL_SECONDS)

    async def drop_presence(self, project_id: str, user_id: str) -> None:
        await self._client.hdel(presence_key(project_id), user_id)

    async def list_presence(self, project_id: str) -> list[dict[str, Any]]:
        raw = await self._client.hgetall(presence_key(project_id))
        return [json.loads(v) for v in raw.values()]

    async def _read_loop(self) -> None:
        # Poll, not listen(): listen() dies on an empty subscription set at startup.
        while True:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
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
