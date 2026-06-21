"""SQL repositories. Every method takes an Executor so it works in or out of a txn."""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..domain.models import CommittedOp, Project, Segment, UndoTarget
from .database import Executor


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    return uuid.UUID(value) if isinstance(value, str) else value


def _segment(row: Any) -> Segment:
    return Segment(
        chunk_id=str(row["chunk_id"]),
        start_time_ms=row["start_time_ms"],
        end_time_ms=row["end_time_ms"],
        speaker_id=str(row["speaker_id"]) if row["speaker_id"] else None,
        text=row["text"],
        position=row["position"],
        deleted=row["deleted"],
        updated_seq=row["updated_seq"],
        updated_by=str(row["updated_by"]) if row["updated_by"] else None,
    )


def _committed_op(row: Any) -> CommittedOp:
    return CommittedOp(
        seq=row["seq"],
        actor=str(row["actor_id"]),
        client_op_id=str(row["client_op_id"]),
        op_type=row["op_type"],
        chunk_id=str(row["chunk_id"]) if row["chunk_id"] else None,
        payload=json.loads(row["payload"]),
        ts=row["created_at"].isoformat(),
    )


def _project(row: Any) -> Project:
    return Project(
        id=str(row["id"]),
        title=row["title"],
        current_seq=row["version"],
        snapshot_seq=row["snapshot_seq"],
        created_at=row["created_at"].isoformat(),
    )


class ProjectRepository:
    def __init__(self, db: Executor):
        self._db = db

    async def create(self, title: str | None) -> Project:
        row = await self._db.fetchrow(
            "INSERT INTO projects (id, title) VALUES ($1, $2) "
            "RETURNING id, title, version, snapshot_seq, created_at",
            uuid.uuid4(),
            title,
        )
        return _project(row)

    async def get(self, project_id: str) -> Project | None:
        row = await self._db.fetchrow(
            "SELECT id, title, version, snapshot_seq, created_at FROM projects WHERE id = $1",
            uuid.UUID(project_id),
        )
        return _project(row) if row else None

    async def bump_version(self, project_id: uuid.UUID) -> int | None:
        return await self._db.fetchval(
            "UPDATE projects SET version = version + 1 WHERE id = $1 RETURNING version",
            project_id,
        )


class SegmentRepository:
    def __init__(self, db: Executor):
        self._db = db

    async def snapshot(self, project_id: str) -> list[Segment]:
        rows = await self._db.fetch(
            "SELECT chunk_id, start_time_ms, end_time_ms, speaker_id, text, position, "
            "deleted, updated_seq, updated_by FROM segments "
            "WHERE project_id = $1 AND deleted = false ORDER BY position, chunk_id",
            uuid.UUID(project_id),
        )
        return [_segment(r) for r in rows]

    async def get(self, chunk_id: str) -> Segment | None:
        row = await self._db.fetchrow(
            "SELECT chunk_id, start_time_ms, end_time_ms, speaker_id, text, position, "
            "deleted, updated_seq, updated_by FROM segments WHERE chunk_id = $1",
            uuid.UUID(chunk_id),
        )
        return _segment(row) if row else None

    async def neighbor_positions(self, project_id: str) -> list[str]:
        rows = await self._db.fetch(
            "SELECT position FROM segments WHERE project_id = $1 AND deleted = false "
            "ORDER BY position, chunk_id",
            uuid.UUID(project_id),
        )
        return [r["position"] for r in rows if r["position"] is not None]

    async def insert_created(
        self,
        chunk_id: uuid.UUID,
        project_id: uuid.UUID,
        seq: int,
        actor: uuid.UUID,
        payload: dict[str, Any],
    ) -> None:
        await self._db.execute(
            "INSERT INTO segments (chunk_id, project_id, start_time_ms, end_time_ms, "
            "speaker_id, text, position, deleted, updated_seq, updated_by, field_seqs) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,false,$8,$9,$10) "
            "ON CONFLICT (chunk_id) DO NOTHING",
            chunk_id,
            project_id,
            payload.get("start_time_ms"),
            payload.get("end_time_ms"),
            _uuid_or_none(payload.get("speaker_id")),
            payload.get("text"),
            payload.get("position"),
            seq,
            actor,
            json.dumps(
                {f: seq for f in ("start_time_ms", "end_time_ms", "speaker_id", "text", "position")}
            ),
        )

    async def mark_deleted(self, chunk_id: uuid.UUID, seq: int, actor: uuid.UUID) -> None:
        await self._db.execute(
            "UPDATE segments SET deleted = true, updated_seq = $2, updated_by = $3 WHERE chunk_id = $1",
            chunk_id,
            seq,
            actor,
        )

    async def lock_field_seqs(self, chunk_id: uuid.UUID) -> dict[str, Any] | None:
        row = await self._db.fetchrow(
            "SELECT field_seqs FROM segments WHERE chunk_id = $1 FOR UPDATE",
            chunk_id,
        )
        if row is None:
            return None
        return json.loads(row["field_seqs"]) if row["field_seqs"] else {}

    async def apply_field_writes(
        self,
        chunk_id: uuid.UUID,
        seq: int,
        actor: uuid.UUID,
        winners: dict[str, Any],
        field_seqs: dict[str, Any],
    ) -> None:
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
        await self._db.execute(
            f"UPDATE segments SET {', '.join(sets)}, updated_seq = ${idx}, "
            f"updated_by = ${idx + 1}, field_seqs = ${idx + 2} WHERE chunk_id = ${idx + 3}",
            *values,
        )


class OperationRepository:
    def __init__(self, db: Executor):
        self._db = db

    async def ops_since(self, project_id: str, last_seq: int) -> list[CommittedOp]:
        rows = await self._db.fetch(
            "SELECT seq, actor_id, client_op_id, op_type, chunk_id, payload, created_at "
            "FROM operations WHERE project_id = $1 AND seq > $2 ORDER BY seq",
            uuid.UUID(project_id),
            last_seq,
        )
        return [_committed_op(r) for r in rows]

    async def last_undoable(self, project_id: str, actor_id: str) -> UndoTarget | None:
        """The actor's most recent op that has not itself been undone and is not an undo."""
        rows = await self._db.fetch(
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
            return UndoTarget(
                seq=r["seq"],
                op_type=r["op_type"],
                chunk_id=str(r["chunk_id"]) if r["chunk_id"] else None,
                payload=json.loads(r["payload"]),
                inverse=json.loads(r["inverse"]),
            )
        return None

    async def find_seq(self, project_id: uuid.UUID, actor_id: uuid.UUID, client_op_id: uuid.UUID) -> int | None:
        return await self._db.fetchval(
            "SELECT seq FROM operations "
            "WHERE project_id = $1 AND actor_id = $2 AND client_op_id = $3",
            project_id,
            actor_id,
            client_op_id,
        )

    async def append(
        self,
        project_id: uuid.UUID,
        seq: int,
        actor_id: uuid.UUID,
        client_op_id: uuid.UUID,
        op_type: str,
        chunk_id: uuid.UUID | None,
        payload: dict[str, Any],
        inverse: dict[str, Any],
    ) -> int | None:
        return await self._db.fetchval(
            "INSERT INTO operations (project_id, seq, actor_id, client_op_id, op_type, "
            "chunk_id, payload, inverse) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
            "ON CONFLICT (project_id, actor_id, client_op_id) DO NOTHING RETURNING seq",
            project_id,
            seq,
            actor_id,
            client_op_id,
            op_type,
            chunk_id,
            json.dumps(payload),
            json.dumps(inverse),
        )
