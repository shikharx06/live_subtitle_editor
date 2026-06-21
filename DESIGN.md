# DESIGN.md — Real-Time Collaborative Subtitles Editor

Backend for real-time, multi-user collaborative editing of a dubbing-studio subtitle
timeline. A *project document* is an ordered list of **segments**, each:

```
{ chunk_id, start_time, end_time, speaker_id, text }
```

Several editors edit one project at once. They must see each other's
create / edit / delete / reorder live, edits must **converge** to one final state
regardless of which server instance a client hit, the document must survive restarts,
and reconnects must neither lose nor duplicate edits.

**Reference stack (mandated baseline):** Python + FastAPI + PostgreSQL. Everything
else (transport, cache, fan-out, topology, convergence model) is a deliberate choice
documented below.

> Section order follows the brief: (1) functional requirements, (2) non-functional
> requirements, (3) back-of-the-envelope, (4) high-level architecture, (5) low-level
> design, (6) technologies + ADRs — followed by scaling, failure modes, and cut scope.

---

## 1. Functional Requirements

### 1.1 In scope (must build / design)

| # | Requirement | Notes |
|---|-------------|-------|
| FR-1 | **Join a project** — a client connects to a project and receives the current full state (snapshot), then a live stream of changes. | Reconnect = same path. |
| FR-2 | **Live edits** — create, edit, delete, and **reorder** segments; all other connected clients see each change live. | Edit = change any of `start_time, end_time, speaker_id, text`. |
| FR-3 | **Convergence** — concurrent edits to the same segment (or the same ordering) end in an identical final state on every client and every server instance. | The core correctness property. |
| FR-4 | **Presence** — show who is online in a project and where each user's cursor is (which segment / field / offset). | Ephemeral. |
| FR-5 | **Persistence** — the document survives server restarts; a reconnecting user gets current state then live updates. | Durable source of truth. |
| FR-6 | **History — undo** — a user can undo their own recent changes. | Undo is itself a recorded, converging operation. |
| FR-7 | **History — activity log** — an auditable log of *who changed what, when*. | Derived from the operation log. |
| FR-8 | **Reconnect safety** — after a dropped connection, the user loses no edits and creates no duplicates. | Idempotent, resumable. |

### 1.2 Explicitly out of scope (for this exercise)

- Authentication / authorization beyond a project-scoped token (assume an auth gateway issues a signed token carrying `user_id` + `project_id` + role).
- Media (audio/video) storage and playback; we edit the *timeline*, not the waveform.
- Rich text / formatting inside `text` (plain UTF-8 only).
- Permanent, regulatory-grade audit retention (we keep a working history, not a 7-year legal archive).
- Branching / merge / version tags (Git-style). Linear history only.

---

## 2. Non-Functional Requirements

| Property | Target | Source / rationale |
|---|---|---|
| **Edit echo latency** | < 150 ms p50, budget to ~120 ms p99 server-side | Stated constraint. |
| **Concurrency per project** | 2–20 concurrent editors | Stated constraint. |
| **Projects** | thousands active simultaneously (design to 10,000) | Stated constraint. |
| **Topology** | N stateless instances behind a load balancer; **no single box** | Stated constraint. |
| **Consistency** | Strong *convergence* (all replicas reach the same state); per-project total order. Cross-project ordering is irrelevant. | FR-3. |
| **Durability** | An **acked** edit is never lost across server/DB restart. | FR-5, FR-8. |
| **Delivery semantics** | At-least-once on the wire + idempotent apply ⇒ **effectively exactly-once** state. | FR-8. |
| **Availability** | Liveness (real-time fan-out) is best-effort; durability + convergence are not sacrificed. Degrade to read-only rather than diverge. | Failure thinking. |
| **Scalability** | Horizontal on the app tier; per-project work is the unit of partitioning. | Topology constraint. |
| **Observability** | Per-op tracing (latency from receive→ack→broadcast), connection counts, lag, conflict/retry rates. | Operability. |
| **Recovery** | Reconnect + full catch-up within a couple of seconds for a normal-sized doc. | FR-8. |

**The defining tension:** *low latency (<150 ms) + horizontal scale (any instance) +
convergence (one final state).* You cannot get all three trivially — the design below
spends a small, bounded amount of latency on a **single per-project serialization point**
to buy convergence cheaply, and keeps that point off the critical broadcast path as it scales.

---

## 3. Back-of-the-Envelope

Working numbers (design point, not absolute peak):

```
Active projects (design)            : 10,000
Editors per project   avg / peak    : 8 / 20
Fraction actively typing at an instant : ~20%
Op model                            : debounced field updates, NOT per-keystroke
Op rate per actively-typing editor  : ~0.5 ops/s
Cursor/presence rate per active user: ~3–5 msgs/s (throttled)
```

### 3.1 Connections

```
avg  : 10,000 × 8   =  80,000 concurrent WebSocket connections
peak : 10,000 × 20  = 200,000 concurrent WebSocket connections
```

An async Python process (uvicorn + uvloop) comfortably holds ~10k–20k mostly-idle WS
connections (memory-bound, tens of KB each).
⇒ **~10–20 app instances** carry the design load. Reasonable.

### 3.2 Write (operation) throughput

```
actively typing = 80,000 × 20%      = 16,000 editors
global op rate  = 16,000 × 0.5 ops/s = ~8,000 ops/s   (typical)
peak (200k conns, 20% active)        = ~20,000 ops/s
```

**Per project:** 20 editors × 20% × 0.5 ≈ **2 ops/s per project**. This is the key
result: *per-project write contention is tiny.* A per-project serialization point
(one row CAS, see §5.4) sees ~2 writes/s — no contention at all.

Each op ⇒ ~3 row writes (append to op log + CAS project version + upsert materialized
segment): `8,000 ops/s × 3 ≈ 24,000 row-writes/s` typical, ~60k/s peak. A single
well-tuned Postgres primary handles the typical load; **peak approaches its ceiling →
this is the first thing to shard (see §7).**

### 3.3 Fan-out (the real volume)

Each committed op is relayed to the other ~7 (avg) editors in the project:

```
edit fan-out     : 8,000 ops/s × 7        ≈  56,000 msgs/s delivered
presence fan-out : 16,000 active × 4 × 7  ≈ 448,000 msgs/s delivered
total delivered  : ~0.5M msgs/s
per instance     : 0.5M / 15 instances    ≈ ~33k msgs/s egress each
```

Edit payload ≈ 500 B JSON ⇒ edit egress ≈ 28 MB/s aggregate. Presence is smaller per
message but higher count; throttling cursor updates is what keeps this sane. All
within async-Python + Redis-pub/sub reach. **Presence, not edits, dominates message
count** — it is deliberately ephemeral and throttled.

### 3.4 Latency budget (<150 ms)

```
client → LB → app                 ~5–20 ms
sequence + append to Postgres     ~2–10 ms   (same AZ, committed)
publish to Redis                  ~1 ms
Redis → subscribing app instances ~1–2 ms
app → recipient client WS         ~5–20 ms
------------------------------------------------
typical total                     ~20–60 ms   ✅ comfortable headroom
```

The variable term is the DB commit. If it spikes, the documented mitigation is
**optimistic broadcast** (broadcast in parallel with the durable append) at the cost of
a sub-millisecond durability window — and ultimately the in-memory authority of §7.

### 3.5 Storage

```
Document size   : ~1,000–2,000 segments × ~200 B  ≈ up to ~400 KB / project  (small!)
Live doc state  : 10,000 × 400 KB                 ≈ ~4 GB total  (fits in RAM fleet-wide)
Op log (raw)    : 8,000 ops/s × 300 B             ≈ 130 GB/day at sustained peak
```

The op log is the only thing that grows without bound, so: **snapshot + compaction**
(keep latest snapshot + recent tail hot for undo/activity; roll older ops to cold
object storage or summarized activity rows). Realistic editing is bursty/work-hours,
so sustained 8k ops/s is a worst case, but retention must be designed, not assumed.
The small document size is what later **unlocks the in-memory per-project authority**
in §7.

---

## 4. High-Level Architecture

> The brief asks for the architecture diagram as item (5); it is placed here, before the
> low-level design, because the LLD refers to these components.

![Architecture diagram](./docs/architecture.svg)

<details>
<summary>Same diagram as ASCII (boxes + arrows), if the SVG doesn't render</summary>

```
                         ┌──────────────────────────────┐
                         │           Clients             │
                         │   (web editor / test harness) │
                         └───────────────┬──────────────┘
                                         │  WSS (WebSocket)  +  REST (bootstrap/auth)
                                         ▼
                         ┌──────────────────────────────┐
                         │   L7 Load Balancer            │   sticky by project_id
                         │   (TLS, WS upgrade)           │   (best-effort, not required)
                         └───────────────┬──────────────┘
                ┌────────────────────────┼────────────────────────┐
                ▼                        ▼                        ▼
   ┌────────────────────┐   ┌────────────────────┐   ┌────────────────────┐
   │  App instance #1    │   │  App instance #2    │   │  App instance #N    │
   │  FastAPI + uvloop   │   │  FastAPI + uvloop   │   │  FastAPI + uvloop   │
   │  ── WS sessions ─── │   │  ── WS sessions ─── │   │  ── WS sessions ─── │
   │  • collab handler   │   │  • collab handler   │   │  • collab handler   │
   │  • presence handler │   │  • presence handler │   │  • presence handler │
   │  STATELESS          │   │  STATELESS          │   │  STATELESS          │
   └─────┬───────┬───────┘   └─────┬───────┬──────┘   └─────┬───────┬──────┘
         │       │                 │       │                │       │
   commit│       │subscribe   commit│       │subscribe commit│       │subscribe
   (ordered      │(fan-out)        │       │               │       │
    append)      ▼                 ▼       ▼               ▼       ▼
         │  ┌─────────────────────────────────────────────────────────┐
         │  │                    Redis                                  │
         │  │  • Pub/Sub: channel per project  → cross-instance fan-out │
         │  │  • Presence: HASH per project (TTL)                       │
         │  │  • Rate limit / connection registry                      │
         │  └─────────────────────────────────────────────────────────┘
         ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │                         PostgreSQL (source of truth)              │
   │  • operations  (append-only op log = activity log + undo basis)   │
   │  • projects    (per-project version counter = the sequencer)      │
   │  • segments    (materialized current state, for fast snapshot)    │
   │  • snapshots   (periodic compaction of the op log)                │
   │  primary + sync replica (HA / failover)                           │
   └─────────────────────────────────────────────────────────────────┘
```

</details>

### 4.1 Request / data flow (an edit)

```
1. Client applies the edit locally (optimistic) and sends:
   {type:"op", client_op_id:UUID, op:"update", chunk_id, fields:{...}, base_seq}

2. App instance validates + authorizes, then COMMITS (one Postgres txn, §5.4):
   a. CAS bump projects.version  →  assigns a per-project monotonic seq
   b. INSERT into operations (idempotent on (project_id, actor_id, client_op_id))
   c. UPSERT into segments (materialized current state)

3. App ACKs the originating client:  {type:"ack", client_op_id, seq}

4. App PUBLISHES the committed op to Redis channel  project:{id}.

5. Every app instance subscribed to that project relays to its local WS sessions:
   {type:"op", seq, actor, op, payload, ts}

6. Each client applies ops in seq order (buffers gaps; a gap → request /sync).
   Because all clients apply the same totally-ordered stream, they CONVERGE.
```

Presence follows the same fan-out path (steps 4–5) but **skips Postgres** — it is
written to a TTL'd Redis hash and published, never persisted.

### 4.2 Why this shape

- **App tier is stateless** → any instance can serve any client; load balancer
  stickiness is a latency optimization, not a correctness requirement.
- **Postgres is the single serialization point per project** → total order ⇒ convergence
  is *trivial and provable*, not a CRDT proof obligation. Per-project contention is ~2
  ops/s (§3.2), so this is cheap today.
- **Redis is fan-out + ephemeral only** → it holds no source of truth, so losing it
  degrades liveness but never loses data; recovery is "catch up from the op log."

---

## 5. Low-Level Design

### 5.1 Data model

```
projects
  id              uuid    PK
  title           text
  version         bigint  NOT NULL DEFAULT 0   -- the per-project sequencer (see §5.4)
  snapshot_seq    bigint  NOT NULL DEFAULT 0   -- op seq the latest snapshot covers
  created_at      timestamptz

segments                                       -- materialized CURRENT state (fast reads)
  chunk_id        uuid    PK
  project_id      uuid    FK → projects(id)
  start_time_ms   integer
  end_time_ms     integer
  speaker_id      uuid
  text            text
  position        text                         -- fractional index / LexoRank ordering key
  deleted         boolean NOT NULL DEFAULT false   -- tombstone (reversible delete)
  updated_seq     bigint                        -- seq of the last op that wrote this row
  updated_by      uuid
  -- per-field "last writer" seqs for field-level LWW (see §5.3):
  field_seqs      jsonb   NOT NULL DEFAULT '{}' -- {"text":1234,"start_time_ms":1230,...}
  INDEX (project_id, position)                  -- ordered read of the document
  INDEX (project_id, deleted)

operations                                     -- APPEND-ONLY: op log = activity log + undo
  id              bigserial PK
  project_id      uuid    FK
  seq             bigint  NOT NULL              -- per-project monotonic (= projects.version after commit)
  actor_id        uuid    NOT NULL
  client_op_id    uuid    NOT NULL              -- client-generated idempotency key
  op_type         text    NOT NULL              -- create | update | delete | move | undo
  chunk_id        uuid
  payload         jsonb   NOT NULL              -- new field values
  inverse         jsonb   NOT NULL              -- prior values, captured for O(1) undo
  created_at      timestamptz NOT NULL DEFAULT now()
  UNIQUE (project_id, seq)                      -- enforces total order
  UNIQUE (project_id, actor_id, client_op_id)   -- enforces idempotency / dedup
  INDEX (project_id, seq)                        -- catch-up / activity log queries

snapshots                                      -- periodic compaction of the op log
  project_id      uuid
  seq             bigint                         -- snapshot reflects ops up to this seq
  doc             jsonb                          -- full ordered segment list
  created_at      timestamptz
  PRIMARY KEY (project_id, seq)
```

Presence lives in **Redis**, not Postgres:

```
HASH  presence:{project_id}   field=user_id   value={cursor:{chunk_id,field,offset}, name, color, ts}
      (each field refreshed on heartbeat; whole key TTL ~30 s; stale users drop off)
PUBSUB channel  project:{project_id}          (edits + presence fan-out)
```

### 5.2 The operation set

Four primitive ops (plus `undo`, which expands into one of them):

| `op_type` | `payload` | `inverse` (for undo) | Convergence handling |
|---|---|---|---|
| `create` | `{chunk_id, position, start_time_ms, end_time_ms, speaker_id, text}` | `{op:"delete", chunk_id}` | New row; `position` from fractional index. |
| `update` | `{chunk_id, fields:{…}}` | `{fields: <prior values>}` | **Per-field LWW** by seq (§5.3). |
| `delete` | `{chunk_id}` | `{op:"create", <prior row>}` | Tombstone (`deleted=true`); reversible. |
| `move`   | `{chunk_id, position}` | `{position: <prior position>}` | LWW on `position` field. |

`create`/`move` use **fractional indexing** (LexoRank-style string keys): inserting
between neighbors `A` and `B` mints a key strictly between them, so two concurrent
inserts at the "same" spot get distinct keys and a deterministic order — no renumbering,
no O(n) rewrite. A background job rebalances keys when they grow too long.

### 5.3 Convergence — why every replica lands in the same state

1. **Total order per project.** Every op gets a unique, gapless `seq` at commit
   (§5.4). The op log `(project_id, seq)` *is* the canonical history.
2. **Deterministic apply.** Every replica (and the materialized `segments` table)
   applies ops strictly in `seq` order. Same inputs, same order ⇒ same output. This is
   the whole convergence argument — no transform functions, no CRDT merge proof.
3. **Field-level LWW for concurrent same-segment edits.** When two users edit the same
   segment, both ops are serialized; the higher-`seq` writer wins **per field**. Editing
   `start_time` and `text` concurrently both survive (different fields). Editing the same
   field concurrently ⇒ last (by seq) wins — a deliberate, documented loss (see ADR-2).
4. **Ordering conflicts** resolve via LWW on the `position` field; fractional keys keep
   concurrent inserts independent.

> Convergence is bought by the *single serialization point*, not by clever client math.
> The cost is that all writes for a project funnel through one row — fine at 2 ops/s/project
> now (§3.2), and moved off the hot path at scale (§7).

### 5.4 The sequencer (commit, one transaction)

No leader election, no Raft — the per-project total order is established by an atomic
**compare-and-swap on `projects.version`**:

```sql
BEGIN;
  -- 1. claim the next seq for THIS project (optimistic concurrency)
  UPDATE projects
     SET version = version + 1
   WHERE id = :project_id
  RETURNING version AS seq;

  -- 2. append the op (idempotent: dup client_op_id violates the unique key → caught → no-op)
  INSERT INTO operations (project_id, seq, actor_id, client_op_id, op_type,
                          chunk_id, payload, inverse)
  VALUES (:project_id, :seq, :actor, :client_op_id, :type, :chunk, :payload, :inverse)
  ON CONFLICT (project_id, actor_id, client_op_id) DO NOTHING;

  -- 3. materialize current state with per-field LWW
  --    (UPSERT into segments; only overwrite a field if :seq > field_seqs[field])
COMMIT;
```

Two ops racing for the same project: both attempt step 1; Postgres row locking
serializes them, each gets a distinct `seq`. No lost updates, no application-level lock,
no separate coordination service. At ~2 ops/s/project this never contends.

### 5.5 WebSocket protocol

```
Client → Server
  hello     {project_id, token, last_seq}          -- join or resume
  op        {client_op_id, op_type, chunk_id, fields|position|...}
  presence  {cursor:{chunk_id, field, offset}}     -- throttled client-side
  undo      {}                                       -- undo my last not-yet-undone op
  ping      {}

Server → Client
  welcome   {snapshot|base_seq, current_seq, you, peers[]}   -- after hello
  sync      {ops:[…]}                                -- catch-up: ops where seq > last_seq
  op        {seq, actor, op_type, payload, ts}       -- live committed change
  ack       {client_op_id, seq}                       -- your op is durable
  presence  {actor, cursor, status:"join|update|leave"}
  error     {code, message}                           -- e.g. STALE_RESUME → full snapshot
```

### 5.6 Join & reconnect (no loss, no duplication)

**Join / resume (`hello`):**
- If `last_seq` is null or `< snapshot_seq` → server sends `welcome` with a **full
  snapshot** (latest snapshot + ops since it), then live.
- If `last_seq >= snapshot_seq` → server sends `sync` with just `ops where seq > last_seq`,
  then live. Cheap delta resume.

**No lost edits:** the client keeps every op it sent but has not yet seen an `ack` for.
On reconnect it **replays** them.
**No duplicates:** replays carry the original `client_op_id`; the
`UNIQUE (project_id, actor_id, client_op_id)` constraint makes re-insertion a no-op, and
the server returns the *existing* `seq` as the `ack`. At-least-once wire delivery +
idempotent apply ⇒ effectively exactly-once state (NFR §2).

**Gap detection:** clients track the highest contiguous `seq` applied. A live `op` whose
`seq` skips ahead means a missed message → the client requests `sync` from its last
contiguous seq. This self-heals a dropped Redis message without any server bookkeeping.

### 5.7 Undo & activity log

- **Activity log (FR-7):** a query on `operations` for the project, ordered by `seq`,
  joined to users — *who* (`actor_id`) did *what* (`op_type`, `payload`) *when*
  (`created_at`). It already exists because persistence is event-sourced.
- **Undo (FR-6):** undo is **not** a state rewind — it is a *new op* built from the
  stored `inverse` of the user's last not-yet-undone op, submitted through the same
  commit + order + broadcast path. Consequences:
  - It converges and is auditable like any other op (it shows up in the activity log).
  - It is **per-user, linear** undo. If someone else changed that field after you, your
    undo (a normal LWW write at a higher seq) becomes the latest value — consistent with
    the LWW model, and explicitly *not* full multi-user selective undo (ADR-2 / §10).
  - O(1) because `inverse` (prior values) was captured at write time.

### 5.8 Presence

Cursor/selection is high-frequency and disposable. Each `presence` message refreshes the
user's field in `presence:{project_id}` (Redis HASH) and is published to the project
channel; the whole key carries a ~30 s TTL refreshed by heartbeat, so a crashed client
silently drops off. Never written to Postgres. Clients throttle to a few updates/sec
(§3.3) — presence dominates message *count*, so throttling it is the main lever keeping
fan-out affordable.

---

## 6. Technologies Used

| Layer | Choice | Role |
|---|---|---|
| Language / runtime | **Python 3.12 + asyncio + uvloop** | Async I/O for many concurrent WS connections. |
| Web / WS framework | **FastAPI + `websockets`/Starlette, served by uvicorn** | Mandated baseline; native async WS + REST bootstrap. |
| Source of truth | **PostgreSQL** (primary + sync replica) | Op log, sequencer, materialized state, snapshots; transactions give atomic seq+append. |
| Cache / fan-out / presence | **Redis** (Pub/Sub + TTL hashes) | Cross-instance broadcast, ephemeral presence, rate limiting. |
| Ordering keys | **Fractional indexing (LexoRank-style)** | Conflict-light reorder/insert. |
| Transport | **WebSocket (WSS)** | Bidirectional, low-latency live edits + presence. |
| Load balancer | **L7 LB with WS upgrade**, sticky-by-project (best-effort) | Spreads connections; stickiness is a latency hint only. |
| Packaging | **Docker Compose** (app ×N, Postgres, Redis) | One-command boot of the vertical slice. |

### Architecture Decision Records

Format per ADR: **Context → Options (≥2 alternatives) → Decision → Trade-off accepted.**

---

#### ADR-1 — Real-time transport: WebSocket

- **Context:** Sub-150 ms bidirectional edits + presence between server and many clients.
- **Options:**
  - **WebSocket** — full-duplex, persistent, low overhead per message.
  - **Server-Sent Events + POST** — simple, HTTP-native, but one-directional (separate POST for writes) and clumsy for presence.
  - **HTTP long-polling** — works everywhere, but high latency/overhead at this connection count.
  - *(WebTransport/HTTP-3 — promising but immature tooling in Python.)*
- **Decision:** **WebSocket (WSS).**
- **Trade-off accepted:** Persistent, stateful connections complicate the load balancer, deploys (drain/rebalance), and scaling vs. the operational simplicity of stateless HTTP. Worth it for latency and a clean bidirectional model.

#### ADR-2 — Convergence model: server-ordered LWW (not CRDT, not OT)

- **Context:** Concurrent same-segment edits must converge to one state on every instance (FR-3), at small doc sizes and 2–20 editors.
- **Options:**
  - **Server total-order + field-level LWW** — one serialization point assigns a global per-project order; deterministic apply ⇒ convergence by construction. Small metadata.
  - **CRDT (Yjs/Automerge, RGA/LSEQ + LWW registers)** — converges without a central authority, enables offline/P2P; but tombstone/metadata overhead, harder undo + "who changed what", heavier mental model.
  - **Operational Transformation (Google-Docs style)** — character-granular merges, but transform functions are famously hard to get right and to maintain.
- **Decision:** **Server total-order + per-field LWW** (+ fractional index for ordering).
- **Trade-off accepted:** Conflict resolution is *field-level last-writer-wins*, so two people typing into the **same field** at the same instant lose one version (the doc still converges). Acceptable for short subtitle lines; a per-field text CRDT is the documented upgrade (§10). We also take on a serialization point (ADR-3) instead of CRDT's coordination-free merge.

#### ADR-3 — Sequencer: Postgres compare-and-swap (stateless app), not a leader

- **Context:** We need a per-project total order. Where does ordering live?
- **Options:**
  - **Postgres CAS on `projects.version`** — app stays stateless; ordering is a one-row atomic update; ~2 ops/s/project ⇒ no contention.
  - **In-memory single-writer authority per project** (owner instance via consistent hashing + Redis lease) — sub-ms sequencing, removes DB from the hot path; but needs ownership handoff, failover, and a durability window.
  - **External consensus (Raft / etcd / Zookeeper)** — strong ordering guarantees, but heavy operationally and overkill at this scale.
- **Decision:** **Postgres CAS now**, with **in-memory authority documented as the scaling evolution (§7).**
- **Trade-off accepted:** Every write touches the DB on the critical path (latency + a global write-throughput ceiling) in exchange for zero leader-election complexity and trivially provable correctness. We pay later (sharding/in-memory authority) only when the numbers force it.

#### ADR-4 — Cross-instance fan-out: Redis Pub/Sub now, partitioned log later

- **Context:** Editors of one project may be on different instances; committed ops must reach all of them.
- **Options:**
  - **Redis Pub/Sub** — trivial channel-per-project fan-out, ~1 ms, already running for presence.
  - **Postgres `LISTEN/NOTIFY`** — no extra infra, but a single notify path through the primary and awkward at high fan-out.
  - **Kafka / Redpanda** — durable, replayable, partitioned; but heavy to operate and overkill while the op log already gives durable replay.
- **Decision:** **Redis Pub/Sub** for live fan-out; the durable **Postgres op log** is the replay/catch-up path.
- **Trade-off accepted:** Redis Pub/Sub is fire-and-forget (at-most-once, no replay) — a dropped message is invisible at the broker. We tolerate this because clients detect `seq` gaps and self-heal via `/sync` from the op log (§5.6). Move to a partitioned log only at 100x (§7).

#### ADR-5 — Persistence model: event-sourced op log + snapshots + materialized state

- **Context:** Need durability, convergence replay, undo, and an activity log.
- **Options:**
  - **Append-only op log + periodic snapshot + materialized `segments` table** — history is first-class; undo, activity log, catch-up, and audit all fall out of it.
  - **CRUD-only mutable `segments` table** — simplest, smallest, but loses history; undo and activity log must be bolted on separately.
  - **Snapshot-on-every-write** — simple reads, but heavy writes and still no per-change history.
- **Decision:** **Op log + snapshots + materialized read table.**
- **Trade-off accepted:** More storage and a compaction/retention job (the op log grows ~130 GB/day at sustained peak, §3.5) in exchange for getting FR-6/FR-7/convergence-replay essentially for free. The materialized table avoids replaying the log on every read.

#### ADR-6 — Document datastore: PostgreSQL

- **Context:** Where do the document, op log, and sequencer live?
- **Options:**
  - **PostgreSQL** — mandated baseline; ACID transactions let us bind *seq assignment + op append + materialization* atomically (ADR-3/§5.4); JSONB for flexible payloads.
  - **MongoDB** — flexible documents and easy sharding, but weaker multi-doc transactional story for our atomic-commit pattern.
  - **DynamoDB / KV** — effortless horizontal scale, but conditional-write-only semantics and no rich queries make the op-log/activity-log story harder; vendor lock-in.
  - *(Redis as primary — rejected: not the durable source of truth we need.)*
- **Decision:** **PostgreSQL** as the single source of truth.
- **Trade-off accepted:** A single primary has a vertical write ceiling (hit first at peak, §3.2/§7); we accept that and plan **hash-sharding by `project_id`** as the evolution, trading the future operational cost for strong consistency and transactions today.

#### ADR-7 — Presence store: Redis with TTL (ephemeral)

- **Context:** "Who's online + cursor position" — high-frequency, disposable.
- **Options:**
  - **Redis TTL hash + Pub/Sub** — fast, auto-expiring, no cleanup job; lost on Redis failure (acceptable — it just repopulates).
  - **In Postgres** — durable but needless write load on the source of truth for throwaway data.
  - **In-process memory only** — fastest, but invisible across instances (breaks the multi-box requirement).
- **Decision:** **Redis TTL hash + Pub/Sub.**
- **Trade-off accepted:** Presence is not durable and can blip on Redis failover; since it's ephemeral and self-refreshing via heartbeat, that's the correct thing to sacrifice.

#### ADR-8 — Reconnect / exactly-once: client idempotency keys + seq resume

- **Context:** Dropped connections must not lose or duplicate edits (FR-8), across instance failover.
- **Options:**
  - **Client-generated `client_op_id` + `UNIQUE` constraint + `last_seq` resume** — dedup at the DB, delta catch-up by seq; works regardless of which instance you reconnect to.
  - **Sticky sessions only** — relies on returning to the same instance; breaks on instance death and doesn't dedup.
  - **Broker-level acks (e.g. a queue)** — exactly-once at the transport, but heavier and still needs app-level dedup for client retries.
- **Decision:** **Idempotency key + seq-based resume.**
- **Trade-off accepted:** Clients must track unacked ops and the last contiguous seq (more client logic), in exchange for stateless, instance-agnostic, no-loss/no-dup reconnects.

---

## 7. Scaling Note — what breaks first, and how it evolves

**Today (design point): ~10k projects, ~80k–200k connections, ~8–20k ops/s.**
Served by ~10–20 stateless app instances, one Postgres primary (+replica), one Redis.

### At 10× (~100k projects, ~1–2M connections, ~80–200k ops/s)

- **First bottleneck: the single Postgres primary on the write path.** Op-log appends +
  per-project CAS + materialization (~3 writes/op) saturate one primary's write IOPS;
  it's on the critical path for the 150 ms budget too.
- **Evolve:**
  1. **Group/commit batching** of op inserts; tune `synchronous_commit`, WAL.
  2. **Read replicas** absorb snapshot/catch-up (`/sync`) reads.
  3. Introduce the **in-memory per-project authority** (ADR-3 alt): the owner instance
     sequences in RAM (sub-ms) and **persists write-behind in batches**, taking the DB
     off the hot path. Convergence still holds (single writer per project).
  4. More app instances; **Redis Cluster** to spread pub/sub channels.
- *Secondary bottleneck:* connection memory across the fleet → add instances / tune ulimits, uvloop.

### At 100× (~1M projects, tens of millions of connections, ~1M ops/s)

- **First bottleneck: a single Postgres can't hold the global op-log write rate; Redis
  Pub/Sub fan-out and a single LB also get hot.**
- **Evolve:**
  1. **Shard Postgres by `hash(project_id)`** — each shard owns a disjoint set of
     projects' op logs + materialized state. Per-project ordering is *local to a shard*,
     so total order is preserved without cross-shard coordination.
  2. **In-memory authority becomes mandatory**, placed by **consistent hashing of
     `project_id`** with a Redis/etcd **lease**; DB is durable append-behind only.
  3. **Replace Redis Pub/Sub with a partitioned log (Kafka/Redpanda)** partitioned by
     `project_id` — durable, replayable fan-out; or sharded Redis with project affinity.
  4. **Project locality / cell routing:** route all editors of a project to the same
     cell (shard + owner + bus partition) so fan-out stays intra-cell; regionalize.
  5. A dedicated **presence service** (its own Redis/bus) so cursor spam can't starve edits.
- **Bottleneck named at each step:** DB write IOPS → *shard*; ordering latency → *in-memory authority*; fan-out volume → *partitioned bus*; connection count → *more cells/edge*; ownership churn → *consistent hashing + lease*.

---

## 8. Failure Modes — what dies, what the user still gets

| Failure | What happens | Guarantee preserved |
|---|---|---|
| **App instance crashes** | Its WS connections drop; clients reconnect (LB → another instance) and `resume` from `last_seq`; unacked ops replayed (idempotent). Presence entries TTL-expire in Redis. App is stateless → nothing lost. | No data loss for **acked** ops; no duplicates; brief reconnect blip. |
| **Postgres primary dies** | Writes fail until failover (sync replica promoted, seconds). During the gap, writes are rejected; clients queue ops locally and replay on recovery; reads can be served from snapshot/replica (read-only). Single primary ⇒ **no split-brain / no divergence**. | Durability of committed (WAL'd/replicated) ops; degrade to **read-only**, never diverge. |
| **Redis dies** | Cross-instance live fan-out + presence stop; same-instance clients still see each other. Postgres untouched. On recovery, clients catch up via `seq`-gap → `/sync` from the op log; presence repopulates from heartbeats. | **No data loss** (Redis holds no source of truth); temporary loss of *liveness* only. |
| **Network partition: app ↔ DB** | That instance can't commit → rejects writes; clients reconnect through a healthy instance. Ordering lives in Postgres, so partitioned instances can't create a conflicting order. | Convergence safe (CP for writes); availability sacrificed on the partitioned side. |
| **Network partition: clients split across instances** (both reach DB+Redis) | They still share the one sequencer and the one channel → they **converge** normally. | Full convergence + liveness. |
| **Crash mid-op (committed but not broadcast)** | The op is durable with its `seq`. Other clients see a `seq` gap on the next op (or on reconnect) and pull it via `/sync`. | No permanent divergence; at-most a sub-second visibility delay. |
| **Duplicate delivery** (Redis redelivery, client replay) | Clients apply by `seq` and ignore already-applied seqs; server dedups by `client_op_id`. | Idempotent apply ⇒ exactly-once state. |
| **Optimistic-broadcast window** (scaling mode, broadcast before durable append) | If the owner dies in the gap, a broadcast op may be un-persisted; clients re-sync to the durable log and the un-persisted op disappears uniformly on all clients. | Convergence preserved; a tiny, bounded durability window — an explicit trade for latency, only in the in-memory-authority mode. |

**Overall stance:** never trade away *durability of acked edits* or *convergence*;
when something breaks, degrade **liveness/availability** (read-only, reconnect blips)
instead of letting clients diverge.

---

## 9. Vertical Slice (what a `docker compose up` would boot)

To match "a thin but working slice," the runnable cut is:

- `docker-compose.yml`: app ×2 (to prove cross-instance fan-out), Postgres, Redis.
- FastAPI app with: `POST /projects` (bootstrap), `GET /projects/{id}` (snapshot),
  `WS /projects/{id}/ws` (join + ops + presence).
- The §5.4 commit path, Redis pub/sub relay, idempotent reconnect, and a **scripted
  multi-client test** that fires concurrent edits at the *same segment via both
  instances* and asserts both clients converge to one final state (the headline property).
- README with ~3 example requests (create project, open WS + send an op, reconnect with
  `last_seq`).

This slice exercises convergence, persistence, and reconnect end-to-end; everything
else in this document is the designed-but-not-built remainder.

---

## 10. What I'd do with more time — and what I knowingly cut

**Cut deliberately (documented, not forgotten):**
- **Per-field character-level co-editing.** Same-field concurrent edits are LWW (one
  version lost). Fine for short subtitle lines; called out in ADR-2.
- **In-memory per-project authority.** Designed in §7 but not built — Postgres CAS is
  correct and simple enough for the slice.
- **Full multi-user selective undo.** Undo is per-user + linear (§5.7), not OT-grade.
- **Durable/replayable fan-out (Kafka).** Redis Pub/Sub + op-log catch-up is sufficient now.
- **Op-log retention/compaction job, snapshot scheduler, fractional-key rebalancer** —
  designed, deferred.
- **AuthN/Z, media, rich text** — out of scope (§1.2).

**With more time (in priority order):**
1. Build the **in-memory authority + write-behind** path and load-test the 10× story.
2. Add a **per-field text CRDT** (e.g. Yjs-style) for true concurrent typing in one field.
3. Implement **snapshot + compaction + cold archival** of the op log; add the rebalancer.
4. Promote fan-out to a **partitioned, replayable bus** and shard Postgres by `project_id`.
5. **Observability**: per-op latency tracing against the 150 ms SLO, conflict/retry and
   reconnect dashboards, presence-vs-edit message-rate split.
6. **Chaos tests**: kill an app instance / Redis / the DB primary mid-edit-storm and
   assert the §8 guarantees automatically.

---

*Summary: a stateless WebSocket app tier, a Postgres per-project total-order sequencer
(event-sourced op log + materialized state), and Redis for ephemeral fan-out/presence.
Convergence is bought cheaply with one serialization point per project (~2 ops/s today);
reconnect safety comes from client idempotency keys + seq-based resume; and the scaling
path moves the sequencer into memory and shards the datastore as the named bottlenecks
arrive. The guiding principle under failure: sacrifice liveness, never durability or
convergence.*
