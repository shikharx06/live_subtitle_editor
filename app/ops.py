from __future__ import annotations

from typing import Any

from . import fracindex


class OpError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def build_create(
    chunk_id: str, fields: dict[str, Any], positions: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    position = fields.get("position")
    if position is None:
        position = fracindex.between(positions[-1] if positions else None, None)
    payload = {
        "chunk_id": chunk_id,
        "position": position,
        "start_time_ms": fields.get("start_time_ms"),
        "end_time_ms": fields.get("end_time_ms"),
        "speaker_id": fields.get("speaker_id"),
        "text": fields.get("text", ""),
    }
    inverse = {"op": "delete", "chunk_id": chunk_id}
    return payload, inverse


def build_update(
    chunk_id: str, fields: dict[str, Any], current: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if current is None:
        raise OpError("UNKNOWN_SEGMENT", f"segment {chunk_id} not found")
    editable = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not editable:
        raise OpError("NO_FIELDS", "update has no editable fields")
    prior = {k: current.get(k) for k in editable}
    return {"chunk_id": chunk_id, "fields": editable}, {"op": "update", "fields": prior}


def build_delete(
    chunk_id: str, current: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if current is None:
        raise OpError("UNKNOWN_SEGMENT", f"segment {chunk_id} not found")
    return {"chunk_id": chunk_id}, {"op": "create", "row": current}


def build_move(
    chunk_id: str,
    current: dict[str, Any] | None,
    before: str | None,
    after: str | None,
    positions: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if current is None:
        raise OpError("UNKNOWN_SEGMENT", f"segment {chunk_id} not found")
    position = fracindex.between(before, after)
    return (
        {"chunk_id": chunk_id, "position": position},
        {"op": "move", "position": current.get("position")},
    )


def build_undo(target: dict[str, Any], positions: list[str]) -> dict[str, Any]:
    """Turn the stored inverse of `target` into a fresh forward op (§5.7)."""
    inv = target["inverse"]
    op = inv.get("op")
    target_seq = target["seq"]

    if op == "delete":
        return {
            "op_type": "delete",
            "chunk_id": inv["chunk_id"],
            "payload": {"chunk_id": inv["chunk_id"], "undoes_seq": target_seq},
            "inverse": {"op": "create", "row": None},
        }
    if op == "create":
        row = inv["row"]
        payload = {
            "chunk_id": row["chunk_id"],
            "position": row.get("position"),
            "start_time_ms": row.get("start_time_ms"),
            "end_time_ms": row.get("end_time_ms"),
            "speaker_id": row.get("speaker_id"),
            "text": row.get("text"),
            "undoes_seq": target_seq,
        }
        return {
            "op_type": "create",
            "chunk_id": row["chunk_id"],
            "payload": payload,
            "inverse": {"op": "delete", "chunk_id": row["chunk_id"]},
        }
    if op == "update":
        return {
            "op_type": "update",
            "chunk_id": target["chunk_id"],
            "payload": {"chunk_id": target["chunk_id"], "fields": inv["fields"], "undoes_seq": target_seq},
            "inverse": {"op": "update", "fields": target["payload"].get("fields", {})},
        }
    if op == "move":
        return {
            "op_type": "move",
            "chunk_id": target["chunk_id"],
            "payload": {"chunk_id": target["chunk_id"], "position": inv["position"], "undoes_seq": target_seq},
            "inverse": {"op": "move", "position": target["payload"].get("position")},
        }
    raise OpError("BAD_UNDO", f"cannot invert op {op!r}")


_UPDATABLE = {"start_time_ms", "end_time_ms", "speaker_id", "text"}
