"""Application orchestration: commit/sequencer, undo, snapshot, catch-up, op building."""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg

from ..domain.models import CommitResult, CommittedOp, Operation, OpType, Project, Segment
from ..domain.operations import OpError, OperationFactory
from ..persistence.database import Executor
from ..persistence.repositories import (
    OperationRepository,
    ProjectRepository,
    SegmentRepository,
)


class ProjectNotFound(Exception):
    pass


class _DuplicateRace(Exception):
    pass


class CollaborationService:
    """Coordinates repositories; owns the single-transaction commit path (§5.4)."""

    def __init__(self, pool: asyncpg.Pool, factory: OperationFactory):
        self._pool = pool
        self._factory = factory

    async def create_project(self, title: str | None) -> Project:
        async with self._pool.acquire() as conn:
            return await ProjectRepository(conn).create(title)

    async def get_project(self, project_id: str) -> Project | None:
        async with self._pool.acquire() as conn:
            return await ProjectRepository(conn).get(project_id)

    async def snapshot(self, project_id: str) -> list[Segment]:
        async with self._pool.acquire() as conn:
            return await SegmentRepository(conn).snapshot(project_id)

    async def ops_since(self, project_id: str, last_seq: int) -> list[CommittedOp]:
        async with self._pool.acquire() as conn:
            return await OperationRepository(conn).ops_since(project_id, last_seq)

    async def build_from_client(
        self, project_id: str, op_type: str, chunk_id: str | None, msg: dict[str, Any]
    ) -> Operation:
        """Build a forward op from a client message (reads neighbors/current segment)."""
        async with self._pool.acquire() as conn:
            segments = SegmentRepository(conn)
            match op_type:
                case OpType.CREATE.value:
                    chunk_id = chunk_id or str(uuid.uuid4())
                    positions = await segments.neighbor_positions(project_id)
                    return self._factory.create(chunk_id, msg.get("fields", {}), positions)
                case OpType.UPDATE.value:
                    current = await segments.get(chunk_id)
                    return self._factory.update(chunk_id, msg.get("fields", {}), current)
                case OpType.DELETE.value:
                    current = await segments.get(chunk_id)
                    return self._factory.delete(chunk_id, current)
                case OpType.MOVE.value:
                    current = await segments.get(chunk_id)
                    return self._factory.move(chunk_id, current, msg.get("before"), msg.get("after"))
                case _:
                    raise OpError("BAD_OP", f"unknown op_type {op_type!r}")

    async def build_undo(self, project_id: str, actor_id: str) -> Operation | None:
        async with self._pool.acquire() as conn:
            target = await OperationRepository(conn).last_undoable(project_id, actor_id)
        if target is None:
            return None
        return self._factory.invert(target)

    async def commit(
        self,
        project_id: str,
        actor_id: str,
        client_op_id: str,
        op: Operation,
    ) -> CommitResult:
        """§5.4 commit. Returns CommitResult; a duplicate client_op_id never burns a seq."""
        pid = uuid.UUID(project_id)
        aid = uuid.UUID(actor_id)
        coid = uuid.UUID(client_op_id)
        cid = uuid.UUID(op.chunk_id) if op.chunk_id else None

        async with self._pool.acquire() as conn:
            try:
                async with conn.transaction():
                    projects = ProjectRepository(conn)
                    operations = OperationRepository(conn)

                    # Dedup before bumping the sequencer so a replay never consumes a seq.
                    existing = await operations.find_seq(pid, aid, coid)
                    if existing is not None:
                        return CommitResult(existing, duplicate=True)

                    seq = await projects.bump_version(pid)
                    if seq is None:
                        raise ProjectNotFound(project_id)

                    inserted = await operations.append(
                        pid, seq, aid, coid, op.op_type, cid, op.payload, op.inverse
                    )
                    if inserted is None:
                        # A concurrent replay won the insert; abort to reclaim the bumped seq.
                        raise _DuplicateRace
                    await self._materialize(conn, pid, seq, aid, op.op_type, cid, op.payload)
                    return CommitResult(seq, duplicate=False)
            except _DuplicateRace:
                existing = await OperationRepository(conn).find_seq(pid, aid, coid)
                return CommitResult(existing, duplicate=True)

    async def _materialize(
        self,
        conn: Executor,
        pid: uuid.UUID,
        seq: int,
        actor: uuid.UUID,
        op_type: str,
        chunk_id: uuid.UUID | None,
        payload: dict[str, Any],
    ) -> None:
        segments = SegmentRepository(conn)
        match op_type:
            case OpType.CREATE.value:
                await segments.insert_created(chunk_id, pid, seq, actor, payload)
            case OpType.DELETE.value:
                await segments.mark_deleted(chunk_id, seq, actor)
            case OpType.MOVE.value:
                await self._apply_fields(segments, chunk_id, seq, actor, {"position": payload["position"]})
            case OpType.UPDATE.value:
                await self._apply_fields(segments, chunk_id, seq, actor, payload.get("fields", {}))

    async def _apply_fields(
        self,
        segments: SegmentRepository,
        chunk_id: uuid.UUID,
        seq: int,
        actor: uuid.UUID,
        fields: dict[str, Any],
    ) -> None:
        """Per-field LWW: overwrite a field only when seq beats its stored field_seq."""
        field_seqs = await segments.lock_field_seqs(chunk_id)
        if field_seqs is None:
            return
        winners = {k: v for k, v in fields.items() if seq > int(field_seqs.get(k, 0))}
        if not winners:
            return
        await segments.apply_field_writes(chunk_id, seq, actor, winners, field_seqs)
