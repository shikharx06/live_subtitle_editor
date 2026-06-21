import asyncio
import json
import os
import urllib.request
import uuid

import pytest

from .client import WSClient

LB_HTTP = os.environ.get("LB_HTTP", "http://localhost:8080")
APP1_HTTP = os.environ.get("APP1_HTTP", "http://localhost:8001")
APP2_HTTP = os.environ.get("APP2_HTTP", "http://localhost:8002")
APP1_WS = APP1_HTTP.replace("http://", "ws://")
APP2_WS = APP2_HTTP.replace("http://", "ws://")
LB_WS = LB_HTTP.replace("http://", "ws://")


def _create_project(title="convergence") -> str:
    req = urllib.request.Request(
        f"{LB_HTTP}/projects",
        data=json.dumps({"title": title}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["id"]


def _get_project(project_id: str) -> dict:
    with urllib.request.urlopen(f"{LB_HTTP}/projects/{project_id}") as resp:
        return json.loads(resp.read())


@pytest.mark.asyncio
async def test_cross_instance_convergence():
    """Concurrent edits to the SAME segment from clients on DIFFERENT instances converge."""
    project_id = _create_project()

    a = WSClient(APP1_WS, project_id, str(uuid.uuid4()))
    b = WSClient(APP2_WS, project_id, str(uuid.uuid4()))
    await a.connect()
    await b.connect()

    chunk_id = str(uuid.uuid4())
    coid = await a.send_op("create", chunk_id=chunk_id, fields={"text": "hello", "start_time_ms": 0, "end_time_ms": 1000})
    create_seq = await a.wait_for_ack(coid)
    await b.wait_until_seq(create_seq)

    n = 20
    tasks = []
    for i in range(n):
        tasks.append(a.send_op("update", chunk_id=chunk_id, fields={"text": f"a-{i}"}))
        tasks.append(b.send_op("update", chunk_id=chunk_id, fields={"text": f"b-{i}"}))
    coids = await asyncio.gather(*tasks)

    last_seqs = await asyncio.gather(*(_ack(c, cid) for c, cid in zip([a, b] * n, coids)))
    final_seq = max(last_seqs)
    await a.wait_until_seq(final_seq)
    await b.wait_until_seq(final_seq)
    await asyncio.sleep(0.3)

    state_a = a.state()[chunk_id]["text"]
    state_b = b.state()[chunk_id]["text"]
    db_state = _get_project(project_id)
    db_text = next(s for s in db_state["segments"] if s["chunk_id"] == chunk_id)["text"]

    assert state_a == state_b == db_text, (state_a, state_b, db_text)

    await a.close()
    await b.close()


@pytest.mark.asyncio
async def test_concurrent_inserts_order_converges():
    """Concurrent creates from two instances yield one identical ordering everywhere."""
    project_id = _create_project("inserts")
    a = WSClient(APP1_WS, project_id)
    b = WSClient(APP2_WS, project_id)
    await a.connect()
    await b.connect()

    tasks = []
    for i in range(10):
        tasks.append(a.send_op("create", fields={"text": f"a-line-{i}"}))
        tasks.append(b.send_op("create", fields={"text": f"b-line-{i}"}))
    await asyncio.gather(*tasks)
    await asyncio.sleep(1.0)

    db_state = _get_project(project_id)
    final_seq = db_state["current_seq"]
    await a.wait_until_seq(final_seq)
    await b.wait_until_seq(final_seq)
    await asyncio.sleep(0.3)

    key = lambda s: (s["position"], s["chunk_id"])
    order_a = [s["chunk_id"] for s in sorted(a.state().values(), key=key)]
    order_b = [s["chunk_id"] for s in sorted(b.state().values(), key=key)]
    order_db = [s["chunk_id"] for s in db_state["segments"]]

    assert order_a == order_b == order_db
    assert len(order_db) == 20
    assert len(set(order_db)) == 20

    await a.close()
    await b.close()


@pytest.mark.asyncio
async def test_reconnect_replay_is_idempotent():
    """Replaying an unacked op with the same client_op_id yields no duplicate, no loss."""
    project_id = _create_project("reconnect")
    user_id = str(uuid.uuid4())
    a = WSClient(APP1_WS, project_id, user_id)
    await a.connect()

    chunk_id = str(uuid.uuid4())
    coid = str(uuid.uuid4())
    replay_msg = {
        "type": "op",
        "client_op_id": coid,
        "op_type": "create",
        "chunk_id": chunk_id,
        "fields": {"text": "v1"},
    }
    await a.send_op("create", chunk_id=chunk_id, fields={"text": "v1"}, client_op_id=coid)
    seq1 = await a.wait_for_ack(coid)

    before = _get_project(project_id)
    op_count_before = before["current_seq"]

    await a.close()
    a2 = WSClient(APP2_WS, project_id, user_id)
    await a2.connect(last_seq=seq1 - 1)
    await a2.replay(replay_msg)
    seq2 = await a2.wait_for_ack(coid)

    assert seq2 == seq1, (seq1, seq2)

    after = _get_project(project_id)
    assert after["current_seq"] == op_count_before, (op_count_before, after["current_seq"])
    matches = [s for s in after["segments"] if s["chunk_id"] == chunk_id]
    assert len(matches) == 1
    assert matches[0]["text"] == "v1"

    await a2.close()


@pytest.mark.asyncio
async def test_resume_delta_after_disconnect():
    """A client that resumes with last_seq gets only the ops it missed, then converges."""
    project_id = _create_project("resume")
    a = WSClient(APP1_WS, project_id)
    b = WSClient(APP2_WS, project_id)
    await a.connect()
    await b.connect()

    chunk_id = str(uuid.uuid4())
    coid = await a.send_op("create", chunk_id=chunk_id, fields={"text": "start"})
    seq0 = await a.wait_for_ack(coid)
    await b.wait_until_seq(seq0)

    await b.close()

    last = seq0
    for i in range(5):
        c = await a.send_op("update", chunk_id=chunk_id, fields={"text": f"while-gone-{i}"})
        last = await a.wait_for_ack(c)

    b2 = WSClient(APP1_WS, project_id, b.user_id)
    await b2.connect(last_seq=seq0)
    await b2.wait_until_seq(last)
    await asyncio.sleep(0.2)

    assert b2.state()[chunk_id]["text"] == "while-gone-4"
    db = _get_project(project_id)
    db_text = next(s for s in db["segments"] if s["chunk_id"] == chunk_id)["text"]
    assert b2.state()[chunk_id]["text"] == db_text

    await a.close()
    await b2.close()


@pytest.mark.asyncio
async def test_via_load_balancer():
    """Two clients through the LB converge (exercises nginx WS upgrade + ip_hash spread)."""
    project_id = _create_project("lb")
    a = WSClient(LB_WS, project_id)
    b = WSClient(LB_WS, project_id)
    await a.connect()
    await b.connect()

    chunk_id = str(uuid.uuid4())
    coid = await a.send_op("create", chunk_id=chunk_id, fields={"text": "lb-test"})
    seq = await a.wait_for_ack(coid)
    await b.wait_until_seq(seq)
    await asyncio.sleep(0.2)

    assert b.state()[chunk_id]["text"] == "lb-test"
    await a.close()
    await b.close()


async def _ack(client: WSClient, coid: str) -> int:
    return await client.wait_for_ack(coid)
