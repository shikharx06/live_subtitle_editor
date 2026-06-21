"""Ephemeral presence in a TTL'd Redis hash (§5.8)."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

PRESENCE_TTL_SECONDS = 30


def presence_key(project_id: str) -> str:
    return f"presence:{project_id}"


class PresenceStore:
    """Per-project presence: a Redis hash refreshed on heartbeat, whole key TTL'd."""

    def __init__(self, client: redis.Redis):
        self._client = client

    async def set(self, project_id: str, user_id: str, value: dict[str, Any]) -> None:
        key = presence_key(project_id)
        await self._client.hset(key, user_id, json.dumps(value))
        await self._client.expire(key, PRESENCE_TTL_SECONDS)

    async def drop(self, project_id: str, user_id: str) -> None:
        await self._client.hdel(presence_key(project_id), user_id)

    async def list(self, project_id: str) -> list[dict[str, Any]]:
        raw = await self._client.hgetall(presence_key(project_id))
        return [json.loads(v) for v in raw.values()]
