from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    instance_id: str
    database_url: str
    redis_url: str
    db_pool_min: int
    db_pool_max: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        instance_id=os.environ.get("INSTANCE_ID", "app"),
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql://subtitles:subtitles@localhost:5432/subtitles",
        ),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        db_pool_min=int(os.environ.get("DB_POOL_MIN", "2")),
        db_pool_max=int(os.environ.get("DB_POOL_MAX", "10")),
    )
