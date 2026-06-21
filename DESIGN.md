# Real-Time Collaborative Subtitle Editor

DESIGN.md

Backend for multiple people editing one subtitle project at the same time. Every edit
shows up on the other clients in near real time and all clients end on the same final
document, even when they are connected to different servers.

---

## 1. Functional Requirements

**Core**

- Multiple users edit one subtitle project at the same time.
- Each user sees the others' edits in near real time.
- Operations: create, update, delete, reorder a segment.
- Presence: who is online, and where their cursor is.
- Persistence: the document survives server restarts.
- A reconnecting user receives the latest state, then live updates.
- History: per-user undo, plus an activity log of who changed what.
- Reconnect is safe: no edit is lost or duplicated.

**Project document**

A project is an ordered list of segments.

```json
{
  "chunk_id": "uuid",
  "start_time_ms": 0,
  "end_time_ms": 3500,
  "speaker_id": "uuid",
  "text": "Hello world"
}
```

---

## 2. Non-Functional Requirements

**Scalability**

- 2–20 concurrent editors per project
- thousands of active projects
- multiple stateless app servers behind a load balancer

**Latency**

- edit propagation < 150 ms

**Consistency**

- concurrent edits converge; every client reaches the same final state
- ordering is per project (cross-project order does not matter)

**Availability**

- survive app-server failures; clients reconnect gracefully
- degrade to read-only rather than diverge

**Durability**

- no acknowledged edit is ever lost

**Maintainability**

- horizontally scalable, stateless app servers

---

## 3. Back-of-the-Envelope

**Assumptions**

```
active projects        = 5,000
editors / project      = 10
```

**Concurrent connections**

```
5,000 × 10
= 50,000 websocket connections
```

A single async (uvloop) process holds ~10k connections → ~5–8 app servers.

**Edit rate**

```
peak    : 1 edit/sec/user   → 50,000 edits/sec
typical : 0.2 edit/sec/user → 10,000 edits/sec
```

Edits are debounced field updates, not per-keystroke.

**Per project**

```
10 editors × 0.2 edit/sec = ~2 edits/sec
```

The sequencer (one row per project, §4) sees ~2 writes/sec — no contention.

**Message size**

```
{ "chunk_id": "...", "field": "text", "value": "..." }  ≈ 300 bytes
```

**Network fanout**

```
10,000 edits/sec × 300 bytes      = 3 MB/sec
× ~10 collaborators per project    ≈ 30 MB/sec
```

Comfortably within Redis Pub/Sub.

**Storage**

```
segment        ≈ 300 bytes
project        ≈ 500 segments × 300 B ≈ 150 KB
5,000 projects ≈ 750 MB
```

Fits comfortably in PostgreSQL. The operation log grows unbounded → snapshot + compact
(keep recent ops for undo/activity, roll the rest into snapshots).

---

## 4. Low-Level Design

### API

```
POST /projects              create a project
GET  /projects/{id}         current snapshot (segments ordered by position)
WS   /projects/{id}/ws      edits, presence, sync
```

### WebSocket messages

Client → server:

```json
{ "type": "hello", "user_id": "uuid", "last_seq": null }

{ "type": "op", "client_op_id": "uuid", "op_type": "create",
  "fields": { "text": "hi", "start_time_ms": 0, "end_time_ms": 1500 } }

{ "type": "op", "client_op_id": "uuid", "op_type": "update",
  "chunk_id": "uuid", "fields": { "text": "edited" } }

{ "type": "op", "client_op_id": "uuid", "op_type": "move",
  "chunk_id": "uuid", "before": "<pos>", "after": "<pos>" }

{ "type": "op", "client_op_id": "uuid", "op_type": "delete", "chunk_id": "uuid" }

{ "type": "presence", "cursor": { "chunk_id": "uuid", "field": "text" } }
{ "type": "undo", "client_op_id": "uuid" }
```

Server → client:

```json
{ "type": "welcome", "you": "uuid", "current_seq": 42, "snapshot": { ... }, "peers": [...] }
{ "type": "sync",    "ops": [ ... ] }
{ "type": "op",      "seq": 43, "actor": "uuid", "op_type": "update", "chunk_id": "uuid", "payload": { ... } }
{ "type": "ack",     "client_op_id": "uuid", "seq": 43 }
{ "type": "presence","actor": "uuid", "cursor": { ... }, "status": "join|update|leave" }
```

### Conflict resolution

Each project has a single sequence number. Every committed edit gets the next one,
assigned atomically (compare-and-swap):

```
UPDATE projects SET version = version + 1 WHERE id = $1 RETURNING version
```

That sequence is the total order. Every server applies ops in `seq` order, so they all
reach the same state.

Within a segment, each field remembers the seq that last wrote it (`field_seqs`). An op
writes a field only if its seq is higher:

```
concurrent edits to the same field      → highest seq wins (last-writer-wins)
concurrent edits to different fields     → both survive
reorder                                  → position is a sortable key; LWW on position
```

### Reconnect

```
every op carries a client_op_id
UNIQUE (project_id, actor_id, client_op_id)  → a replay is a no-op (returns the old seq)
on reconnect the client sends last_seq → server replays ops where seq > last_seq
```

At-least-once delivery + idempotent apply = no lost or duplicated edits.

### Undo

Each op stores its inverse. Undo submits the inverse as a normal op (so it is ordered,
broadcast, and logged like any other edit).

```
update  { text: A → B }      inverse  { text: B → A }
create                       inverse  delete
delete                       inverse  create (from stored row)
```

---

## 5. High-Level Architecture

![Architecture diagram](docs/architecture.svg)

### Request flow

1. User makes an edit.
2. App server validates it.
3. Edit is committed to PostgreSQL (sequence assigned, op appended, segment updated) — one transaction.
4. App server acks the sender.
5. The committed op is published to the project's Redis channel.
6. Every app server with clients on that project relays it to them.
7. Clients apply ops in `seq` order → converge.

### Data model

```sql
CREATE TABLE projects (
    id           UUID PRIMARY KEY,
    title        TEXT,
    version      BIGINT NOT NULL DEFAULT 0,   -- the per-project sequencer
    snapshot_seq BIGINT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE segments (
    chunk_id      UUID PRIMARY KEY,
    project_id    UUID NOT NULL REFERENCES projects(id),
    start_time_ms INTEGER,
    end_time_ms   INTEGER,
    speaker_id    UUID,
    text          TEXT,
    position      TEXT,                        -- sortable ordering key (LexoRank)
    deleted       BOOLEAN NOT NULL DEFAULT false,
    updated_seq   BIGINT,
    updated_by    UUID,
    field_seqs    JSONB NOT NULL DEFAULT '{}'  -- last seq per field, for LWW
);

CREATE TABLE operations (
    id           BIGSERIAL PRIMARY KEY,
    project_id   UUID NOT NULL REFERENCES projects(id),
    seq          BIGINT NOT NULL,
    actor_id     UUID NOT NULL,
    client_op_id UUID NOT NULL,
    op_type      TEXT NOT NULL,
    chunk_id     UUID,
    payload      JSONB NOT NULL,
    inverse      JSONB NOT NULL,               -- for undo
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, seq),
    UNIQUE (project_id, actor_id, client_op_id)
);

CREATE TABLE snapshots (
    project_id UUID NOT NULL,
    seq        BIGINT NOT NULL,
    doc        JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, seq)
);
```

The `operations` table is the source of truth, the activity log, and the basis for undo.
`segments` is a materialized view of the current state, for fast reads.

---

## 6. Technologies & ADRs

### ADR-1: WebSockets vs polling

- **Decision:** WebSockets.
- **Why:** bidirectional, low latency, good fit for live editing + presence.
- **Trade-off:** stateful connections need management (drain on deploy, reconnect).

### ADR-2: PostgreSQL as source of truth

- **Alternatives:** MongoDB, Cassandra.
- **Decision:** PostgreSQL.
- **Why:** transactions let us assign the sequence + append the op + update the segment atomically; JSONB for payloads; reference stack.
- **Trade-off:** a single primary's write throughput is the eventual ceiling (shard later).

### ADR-3: Redis Pub/Sub vs Kafka

- **Alternatives:** Kafka, RabbitMQ.
- **Decision:** Redis Pub/Sub.
- **Why:** the need is low-latency fanout; simpler to run; already used for presence.
- **Trade-off:** messages aren't durable. Acceptable — PostgreSQL already stores every edit, and clients catch up from the op log.

### ADR-4: Monolith vs microservices

- **Decision:** modular monolith.
- **Why:** faster to build, easier to debug, fits the scope; clean internal layers (api / services / domain / persistence / realtime).
- **Trade-off:** components can't scale independently.

### ADR-5: Convergence — server order + field-level LWW

- **Alternatives:** OT, CRDT.
- **Decision:** one server-assigned sequence per project + per-field last-writer-wins.
- **Why:** subtitle docs are naturally segmented; with few editors this is simple and gives deterministic convergence without OT/CRDT machinery.
- **Trade-off:** two people typing in the *same field* at once → one version is overwritten. Acceptable at this editor count (a per-field text CRDT is the upgrade).

### ADR-6: Redis presence store

- **Alternatives:** PostgreSQL, in-memory per server.
- **Decision:** Redis (TTL hash).
- **Why:** shared across servers, auto-expiring, fast.
- **Trade-off:** presence is ephemeral — lost on Redis failure, repopulates on the next heartbeat.

### ADR-7: Fractional ordering

- **Decision:** store a sortable position key per segment; insert/move = a key between the neighbours.
- **Why:** reorder touches one row instead of renumbering the whole list.
- **Trade-off:** keys grow over time; occasional rebalancing needed.

### ADR-8: Operation log + snapshots

- **Decision:** append every op; snapshot the document periodically.
- **Why:** gives undo, the activity log, catch-up, and crash recovery for free.
- **Trade-off:** extra storage + a compaction job.

---

## Failure Analysis

**App server dies**

- *Impact:* its clients disconnect.
- *Guarantee:* clients reconnect to another server and resume from `last_seq`; nothing is lost (servers are stateless).

**Redis dies**

- *Impact:* cross-server fanout and presence stop.
- *Guarantee:* no data loss; writes still go to PostgreSQL; clients re-sync from the op log on recovery.

**PostgreSQL dies**

- *Impact:* writes are rejected until failover.
- *Guarantee:* no acknowledged edit is lost; the system degrades to read-only rather than diverging.

---

## Scaling Roadmap

**10×**

```
bottleneck : Redis fanout
mitigation : Redis Cluster, channel sharding by project
```

**100×**

```
bottleneck : PostgreSQL write throughput
mitigation : shard Postgres by project_id, in-memory per-project sequencer
             with write-behind, partitioned event bus (Kafka/Redpanda)
```

---

## Future Improvements

1. Character-level CRDT for same-field co-editing (e.g. Yjs).
2. In-memory per-project authority with write-behind persistence.
3. Snapshot + compaction job; position-key rebalancer.
4. Durable, replayable event bus (Kafka).
5. Observability: per-op latency, conflict/retry, reconnect dashboards.
6. Chaos tests for the failure modes above.

## Deliberately Out of Scope

1. Multi-region active-active replication.
2. Offline editing.
3. Character-level OT.
4. AI-assisted subtitle generation.
5. Enterprise RBAC.
