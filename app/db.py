from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg


async def create_pool(dsn: str, min_size: int, max_size: int) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)


async def create_project(pool: asyncpg.Pool, title: str | None) -> dict[str, Any]:
    project_id = uuid.uuid4()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO projects (id, title) VALUES ($1, $2) "
            "RETURNING id, title, version, snapshot_seq, created_at",
            project_id,
            title,
        )
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "current_seq": row["version"],
        "snapshot_seq": row["snapshot_seq"],
        "created_at": row["created_at"].isoformat(),
    }


async def get_project(pool: asyncpg.Pool, project_id: str) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, title, version, snapshot_seq, created_at FROM projects WHERE id = $1",
            uuid.UUID(project_id),
        )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "current_seq": row["version"],
        "snapshot_seq": row["snapshot_seq"],
        "created_at": row["created_at"].isoformat(),
    }


async def get_snapshot(pool: asyncpg.Pool, project_id: str) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT chunk_id, start_time_ms, end_time_ms, speaker_id, text, position, "
            "deleted, updated_seq, updated_by FROM segments "
            "WHERE project_id = $1 AND deleted = false ORDER BY position, chunk_id",
            uuid.UUID(project_id),
        )
    return [_segment_row(r) for r in rows]


async def get_segment(
    pool: asyncpg.Pool, chunk_id: str
) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT chunk_id, start_time_ms, end_time_ms, speaker_id, text, position, "
            "deleted, updated_seq, updated_by FROM segments WHERE chunk_id = $1",
            uuid.UUID(chunk_id),
        )
    return _segment_row(row) if row else None


async def get_ops_since(
    pool: asyncpg.Pool, project_id: str, last_seq: int
) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT seq, actor_id, client_op_id, op_type, chunk_id, payload, created_at "
            "FROM operations WHERE project_id = $1 AND seq > $2 ORDER BY seq",
            uuid.UUID(project_id),
            last_seq,
        )
    return [_op_row(r) for r in rows]


async def last_undoable_op(
    pool: asyncpg.Pool, project_id: str, actor_id: str
) -> dict[str, Any] | None:
    """The actor's most recent op that has not itself been undone and is not an undo."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT seq, op_type, chunk_id, payload, inverse FROM operations "
            "WHERE project_id = $1 AND actor_id = $2 ORDER BY seq DESC",
            uuid.UUID(project_id),
            uuid.UUID(actor_id),
        )
    undone_seqs: set[int] = set()
    for r in rows:
        if r["op_type"] == "undo":
            payload = json.loads(r["payload"])
            target = payload.get("undoes_seq")
            if target is not None:
                undone_seqs.add(int(target))
    for r in rows:
        if r["op_type"] == "undo":
            continue
        if r["seq"] in undone_seqs:
            continue
        return {
            "seq": r["seq"],
            "op_type": r["op_type"],
            "chunk_id": str(r["chunk_id"]) if r["chunk_id"] else None,
            "payload": json.loads(r["payload"]),
            "inverse": json.loads(r["inverse"]),
        }
    return None


async def neighbor_positions(
    pool: asyncpg.Pool, project_id: str
) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT position FROM segments WHERE project_id = $1 AND deleted = false "
            "ORDER BY position, chunk_id",
            uuid.UUID(project_id),
        )
    return [r["position"] for r in rows if r["position"] is not None]


async def commit_op(
    pool: asyncpg.Pool,
    project_id: str,
    actor_id: str,
    client_op_id: str,
    op_type: str,
    chunk_id: str | None,
    payload: dict[str, Any],
    inverse: dict[str, Any],
) -> dict[str, Any]:
    """§5.4 commit. Returns {seq, duplicate}; a duplicate client_op_id never burns a seq."""
    pid = uuid.UUID(project_id)
    aid = uuid.UUID(actor_id)
    coid = uuid.UUID(client_op_id)
    cid = uuid.UUID(chunk_id) if chunk_id else None

    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                # Dedup before bumping the sequencer so a replay never consumes a seq.
                existing = await conn.fetchval(
                    "SELECT seq FROM operations "
                    "WHERE project_id = $1 AND actor_id = $2 AND client_op_id = $3",
                    pid,
                    aid,
                    coid,
                )
                if existing is not None:
                    return {"seq": existing, "duplicate": True}

                seq = await conn.fetchval(
                    "UPDATE projects SET version = version + 1 WHERE id = $1 RETURNING version",
                    pid,
                )
                if seq is None:
                    raise ValueError("project not found")

                inserted = await conn.fetchval(
                    "INSERT INTO operations (project_id, seq, actor_id, client_op_id, op_type, "
                    "chunk_id, payload, inverse) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
                    "ON CONFLICT (project_id, actor_id, client_op_id) DO NOTHING RETURNING seq",
                    pid,
                    seq,
                    aid,
                    coid,
                    op_type,
                    cid,
                    json.dumps(payload),
                    json.dumps(inverse),
                )
                if inserted is None:
                    # A concurrent replay won the insert; abort to reclaim the bumped seq.
                    raise _DuplicateRace
                await _materialize(conn, pid, seq, aid, op_type, cid, payload)
                return {"seq": seq, "duplicate": False}
        except _DuplicateRace:
            existing = await conn.fetchval(
                "SELECT seq FROM operations "
                "WHERE project_id = $1 AND actor_id = $2 AND client_op_id = $3",
                pid,
                aid,
                coid,
            )
            return {"seq": existing, "duplicate": True}


class _DuplicateRace(Exception):
    pass


async def _materialize(conn, pid, seq, actor, op_type, chunk_id, payload) -> None:
    if op_type == "create":
        await conn.execute(
            "INSERT INTO segments (chunk_id, project_id, start_time_ms, end_time_ms, "
            "speaker_id, text, position, deleted, updated_seq, updated_by, field_seqs) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,false,$8,$9,$10) "
            "ON CONFLICT (chunk_id) DO NOTHING",
            chunk_id,
            pid,
            payload.get("start_time_ms"),
            payload.get("end_time_ms"),
            _uuid_or_none(payload.get("speaker_id")),
            payload.get("text"),
            payload.get("position"),
            seq,
            actor,
            json.dumps(
                {
                    f: seq
                    for f in (
                        "start_time_ms",
                        "end_time_ms",
                        "speaker_id",
                        "text",
                        "position",
                    )
                }
            ),
        )
        return

    if op_type == "delete":
        await conn.execute(
            "UPDATE segments SET deleted = true, updated_seq = $2, updated_by = $3 "
            "WHERE chunk_id = $1",
            chunk_id,
            seq,
            actor,
        )
        return

    if op_type == "move":
        await _apply_fields(conn, chunk_id, seq, actor, {"position": payload["position"]})
        return

    if op_type == "update":
        await _apply_fields(conn, chunk_id, seq, actor, payload.get("fields", {}))
        return


async def _apply_fields(conn, chunk_id, seq, actor, fields: dict[str, Any]) -> None:
    """Per-field LWW: overwrite a field only when seq beats its stored field_seq."""
    row = await conn.fetchrow(
        "SELECT field_seqs FROM segments WHERE chunk_id = $1 FOR UPDATE",
        chunk_id,
    )
    if row is None:
        return
    field_seqs = json.loads(row["field_seqs"]) if row["field_seqs"] else {}

    winners = {k: v for k, v in fields.items() if seq > int(field_seqs.get(k, 0))}
    if not winners:
        return

    column_map = {
        "start_time_ms": "start_time_ms",
        "end_time_ms": "end_time_ms",
        "speaker_id": "speaker_id",
        "text": "text",
        "position": "position",
    }
    sets = []
    values: list[Any] = []
    idx = 1
    for field, value in winners.items():
        col = column_map.get(field)
        if col is None:
            continue
        sets.append(f"{col} = ${idx}")
        values.append(_uuid_or_none(value) if field == "speaker_id" else value)
        field_seqs[field] = seq
        idx += 1
    if not sets:
        return

    values.extend([seq, actor, json.dumps(field_seqs), chunk_id])
    await conn.execute(
        f"UPDATE segments SET {', '.join(sets)}, updated_seq = ${idx}, "
        f"updated_by = ${idx + 1}, field_seqs = ${idx + 2} WHERE chunk_id = ${idx + 3}",
        *values,
    )


def _uuid_or_none(value):
    if value is None:
        return None
    return uuid.UUID(value) if isinstance(value, str) else value


def _segment_row(r) -> dict[str, Any]:
    return {
        "chunk_id": str(r["chunk_id"]),
        "start_time_ms": r["start_time_ms"],
        "end_time_ms": r["end_time_ms"],
        "speaker_id": str(r["speaker_id"]) if r["speaker_id"] else None,
        "text": r["text"],
        "position": r["position"],
        "deleted": r["deleted"],
        "updated_seq": r["updated_seq"],
        "updated_by": str(r["updated_by"]) if r["updated_by"] else None,
    }


def _op_row(r) -> dict[str, Any]:
    return {
        "seq": r["seq"],
        "actor": str(r["actor_id"]),
        "client_op_id": str(r["client_op_id"]),
        "op_type": r["op_type"],
        "chunk_id": str(r["chunk_id"]) if r["chunk_id"] else None,
        "payload": json.loads(r["payload"]),
        "ts": r["created_at"].isoformat(),
    }
