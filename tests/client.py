import asyncio
import json
import uuid

import websockets


class WSClient:
    """Minimal protocol client: tracks applied ops by seq and unacked ops for replay."""

    def __init__(self, base_url: str, project_id: str, user_id: str | None = None):
        self.url = f"{base_url}/projects/{project_id}/ws"
        self.user_id = user_id or str(uuid.uuid4())
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.applied: dict[str, dict] = {}
        self.acks: dict[str, int] = {}
        self.unacked: dict[str, dict] = {}
        self.welcome: dict | None = None
        self.observed_seq: int = 0
        self._reader: asyncio.Task | None = None

    async def connect(self, last_seq: int | None = None) -> None:
        self.ws = await websockets.connect(self.url, max_size=4 * 1024 * 1024)
        await self.ws.send(json.dumps({"type": "hello", "user_id": self.user_id, "last_seq": last_seq}))
        self._reader = asyncio.create_task(self._read_loop())
        while self.welcome is None:
            await asyncio.sleep(0.01)

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                mtype = msg.get("type")
                if mtype == "welcome":
                    self.welcome = msg
                    for seg in msg.get("snapshot", {}).get("segments", []):
                        self.applied[seg["chunk_id"]] = seg
                elif mtype == "sync":
                    for op in msg["ops"]:
                        self._apply(op)
                elif mtype == "op":
                    self._apply(msg)
                elif mtype == "ack":
                    self.acks[msg["client_op_id"]] = msg["seq"]
                    self.unacked.pop(msg["client_op_id"], None)
        except websockets.ConnectionClosed:
            pass

    def _apply(self, op: dict) -> None:
        op_type = op.get("op_type")
        payload = op.get("payload", {})
        if op.get("seq"):
            self.observed_seq = max(self.observed_seq, op["seq"])
        chunk_id = op.get("chunk_id") or payload.get("chunk_id")
        if op_type == "create":
            self.applied[chunk_id] = {
                "chunk_id": chunk_id,
                "position": payload.get("position"),
                "start_time_ms": payload.get("start_time_ms"),
                "end_time_ms": payload.get("end_time_ms"),
                "speaker_id": payload.get("speaker_id"),
                "text": payload.get("text"),
                "deleted": False,
            }
        elif op_type == "update":
            seg = self.applied.setdefault(chunk_id, {"chunk_id": chunk_id})
            seg.update(payload.get("fields", {}))
        elif op_type == "delete":
            seg = self.applied.setdefault(chunk_id, {"chunk_id": chunk_id})
            seg["deleted"] = True
        elif op_type == "move":
            seg = self.applied.setdefault(chunk_id, {"chunk_id": chunk_id})
            seg["position"] = payload.get("position")

    async def send_op(self, op_type: str, *, chunk_id=None, fields=None, before=None, after=None, client_op_id=None) -> str:
        client_op_id = client_op_id or str(uuid.uuid4())
        msg = {"type": "op", "client_op_id": client_op_id, "op_type": op_type}
        if chunk_id:
            msg["chunk_id"] = chunk_id
        if fields:
            msg["fields"] = fields
        if before is not None:
            msg["before"] = before
        if after is not None:
            msg["after"] = after
        self.unacked[client_op_id] = msg
        await self.ws.send(json.dumps(msg))
        return client_op_id

    async def replay(self, msg: dict) -> None:
        self.unacked[msg["client_op_id"]] = msg
        await self.ws.send(json.dumps(msg))

    async def wait_for_ack(self, client_op_id: str, timeout: float = 5.0) -> int:
        deadline = asyncio.get_event_loop().time() + timeout
        while client_op_id not in self.acks:
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(f"no ack for {client_op_id}")
            await asyncio.sleep(0.01)
        return self.acks[client_op_id]

    async def wait_until_seq(self, seq: int, timeout: float = 5.0) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while self._highest_seq() < seq:
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(f"never reached seq {seq}, at {self._highest_seq()}")
            await asyncio.sleep(0.01)

    def _highest_seq(self) -> int:
        return max(max(self.acks.values(), default=0), self.observed_seq)

    def state(self) -> dict[str, dict]:
        return {cid: seg for cid, seg in self.applied.items() if not seg.get("deleted")}

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()
        if self._reader:
            self._reader.cancel()
