"""asyncpg pool factory and the Executor protocol shared by Pool and Connection."""

from __future__ import annotations

from typing import Any, Protocol

import asyncpg


class Executor(Protocol):
    """The subset of asyncpg satisfied by both Pool and Connection."""

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]: ...
    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


async def create_pool(dsn: str, min_size: int, max_size: int) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)
