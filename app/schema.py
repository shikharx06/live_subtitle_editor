SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id           uuid PRIMARY KEY,
    title        text,
    version      bigint NOT NULL DEFAULT 0,
    snapshot_seq bigint NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS segments (
    chunk_id      uuid PRIMARY KEY,
    project_id    uuid NOT NULL REFERENCES projects(id),
    start_time_ms integer,
    end_time_ms   integer,
    speaker_id    uuid,
    text          text,
    position      text,
    deleted       boolean NOT NULL DEFAULT false,
    updated_seq   bigint,
    updated_by    uuid,
    field_seqs    jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS segments_project_position_idx ON segments (project_id, position);
CREATE INDEX IF NOT EXISTS segments_project_deleted_idx ON segments (project_id, deleted);

CREATE TABLE IF NOT EXISTS operations (
    id           bigserial PRIMARY KEY,
    project_id   uuid NOT NULL REFERENCES projects(id),
    seq          bigint NOT NULL,
    actor_id     uuid NOT NULL,
    client_op_id uuid NOT NULL,
    op_type      text NOT NULL,
    chunk_id     uuid,
    payload      jsonb NOT NULL,
    inverse      jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, seq),
    UNIQUE (project_id, actor_id, client_op_id)
);
CREATE INDEX IF NOT EXISTS operations_project_seq_idx ON operations (project_id, seq);

CREATE TABLE IF NOT EXISTS snapshots (
    project_id uuid NOT NULL,
    seq        bigint NOT NULL,
    doc        jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, seq)
);
"""


async def bootstrap_schema(pool) -> None:
    async with pool.acquire() as conn:
        # Serialize concurrent instances: CREATE TABLE IF NOT EXISTS races on pg_type.
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(913355)")
            await conn.execute(SCHEMA_SQL)
