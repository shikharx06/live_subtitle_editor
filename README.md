# Real-Time Collaborative Subtitles Editor — Vertical Slice

A thin-but-working backend slice implementing the design in [`DESIGN.md`](./DESIGN.md):
Postgres per-project total-order sequencer (event-sourced op log + materialized state),
Redis pub/sub for cross-instance fan-out and ephemeral presence, FastAPI + WebSocket
app tier, two app instances behind an nginx L7 load balancer.

It exercises the headline properties end-to-end: **cross-instance convergence**,
**persistence**, and **no-loss / no-duplicate reconnect**.

## Topology

```
clients ──► nginx (:8080, WS upgrade, ip_hash) ──► app1 (:8001) ─┐
                                                  └► app2 (:8002) ─┤
                                                  Postgres ◄───────┘
                                                  Redis
```

Postgres and Redis are reachable only on the internal compose network (no host ports), so
the stack boots even if you already run Postgres/Redis locally. Apps are on `:8001`/`:8002`
and the LB on `:8080`.

Two app instances are required to prove cross-instance convergence: a client on `app1`
and a client on `app2` editing the same segment converge to one state.

## One-command boot

```bash
docker compose up -d --build      # boots postgres, redis, app1, app2, nginx
docker compose ps                 # wait until app1/app2 are healthy
```

Schema is bootstrapped idempotently on app startup (`CREATE TABLE IF NOT EXISTS …`),
so no migration step is needed.

Tear down:

```bash
docker compose down -v
```

## Web demo (browser)

With the stack up, open the editor in your browser:

| URL | Connects to |
|---|---|
| <http://localhost:8001/> | app1 directly |
| <http://localhost:8002/> | app2 directly |
| <http://localhost:8080/> | via the nginx load balancer |

**To see cross-instance convergence live:**

1. Open <http://localhost:8001/> and click **Create new project**.
2. The page shows peer links — click the **app2 (:8002)** link to open the *same project*
   on the other instance in a new tab (or copy the URL and swap `8001`→`8002`).
3. Edit in either tab — add/edit/reorder/delete segments, change speaker, undo. Each tab
   is a different user (colored chip), connected to a **different server instance**. Edits
   echo live and both tabs converge to one state.

The page is server-authoritative (it renders committed ops from the broadcast), shows
**presence** (who's online + which segment each peer is editing), and a live **activity
log** built from the op stream. Pull a container (`docker stop subtitle_editor-app1-1`)
mid-edit to watch a tab reconnect and resume without losing edits.

The page is a single self-contained file ([`app/static/index.html`](app/static/index.html))
served at `/`; it speaks the exact WebSocket protocol below.

### Full Next.js client + Playwright simulations (`web/`)

A richer **Next.js (App Router) + TypeScript + Tailwind** client lives in [`web/`](web/),
with a **Playwright** suite that spawns two users on two different backend instances
(A→app1, B→app2) and simulates every operation, asserting cross-instance convergence
(including a randomized 30-op stress sim that checks both views match the backend DB).

```bash
cd web
npm install
npx playwright install chromium
npm run dev        # open http://localhost:3000  (or 3100 if 3000 is taken)
npx playwright test   # 9 two-user cross-instance simulations
```

Requires the Docker stack (above) to be running. See [`web/README.md`](web/README.md) for details.

## Run the convergence test

The tests open WebSocket clients to **both instances directly** (`:8001`, `:8002`) and
**through the load balancer** (`:8080`), fire concurrent edits to the same segment, and
assert every client and the DB converge.

```bash
# from a venv with the test deps (uv venv .venv && uv pip install -r requirements.txt)
.venv/bin/python -m pytest tests/test_convergence.py -v
```

Tests (in `tests/test_convergence.py`):

| Test | Property proven |
|---|---|
| `test_cross_instance_convergence` | concurrent same-segment edits from app1 + app2 → identical final state on both clients and in Postgres |
| `test_concurrent_inserts_order_converges` | concurrent creates from both instances → one identical ordering everywhere (fractional index) |
| `test_reconnect_replay_is_idempotent` | replaying an unacked op with the same `client_op_id` → no duplicate, no extra seq, no loss |
| `test_resume_delta_after_disconnect` | reconnect with `last_seq` → only the missed ops are replayed, client converges |
| `test_via_load_balancer` | two clients through nginx converge (WS upgrade + spread) |

Override endpoints with env vars if you remapped ports: `LB_HTTP`, `APP1_HTTP`, `APP2_HTTP`.

`tests/test_fracindex.py` runs standalone (no stack needed):
`.venv/bin/python -m pytest tests/test_fracindex.py`.

## Example requests

### 1. Create a project (REST, via the LB)

```bash
curl -s -X POST http://localhost:8080/projects \
  -H 'content-type: application/json' \
  -d '{"title":"My dub"}'
# {"id":"<project_id>","title":"My dub","current_seq":0,"snapshot_seq":0,"created_at":"..."}
```

Read the ordered snapshot + current seq:

```bash
curl -s http://localhost:8080/projects/<project_id>
# {"id":"...","current_seq":N,"snapshot_seq":0,"segments":[ ...ordered by position... ]}
```

### 2. Open a WebSocket and send an op

Connect to `ws://localhost:8080/projects/<project_id>/ws` (or `:8001`/`:8002` to pin an
instance). First message must be `hello`:

```json
{ "type": "hello", "user_id": "11111111-1111-1111-1111-111111111111", "last_seq": null }
```

Server replies `welcome` with the snapshot + `current_seq`, then live `op`s. Create a
segment:

```json
{ "type": "op", "client_op_id": "<uuid>", "op_type": "create",
  "fields": { "text": "hello world", "start_time_ms": 0, "end_time_ms": 1500 } }
```

Server acks the originator and broadcasts to everyone:

```json
{ "type": "ack", "client_op_id": "<uuid>", "seq": 1 }
{ "type": "op", "seq": 1, "actor": "...", "op_type": "create", "chunk_id": "...", "payload": {...} }
```

Update a field (per-field LWW by seq), move (fractional reorder), delete (tombstone),
presence, undo:

```json
{ "type": "op", "client_op_id": "<uuid>", "op_type": "update",
  "chunk_id": "<chunk_id>", "fields": { "text": "edited" } }
{ "type": "op", "client_op_id": "<uuid>", "op_type": "move",
  "chunk_id": "<chunk_id>", "before": "a", "after": "b" }
{ "type": "presence", "cursor": { "chunk_id": "<chunk_id>", "field": "text", "offset": 4 } }
{ "type": "undo" }
```

### 3. Reconnect with `last_seq` (resume, no loss / no dup)

Reconnect (to any instance) with the highest contiguous seq you applied:

```json
{ "type": "hello", "user_id": "11111111-1111-1111-1111-111111111111", "last_seq": 7 }
```

- `last_seq >= snapshot_seq` → server sends `sync` with only `ops where seq > last_seq`.
- `last_seq` null or `< snapshot_seq` → server sends `welcome` with a full snapshot.

Then replay any op you never saw an `ack` for, reusing its original `client_op_id`. The
`UNIQUE (project_id, actor_id, client_op_id)` constraint makes re-insertion a no-op and
the server returns the *existing* seq — at-least-once wire + idempotent apply ⇒
effectively exactly-once state.

## Layout

```
app/
  main.py        FastAPI app: lifespan, REST, WS protocol (§5.5)
  db.py          asyncpg pool + the §5.4 commit path (CAS bump, idempotent append, LWW upsert)
  ops.py         payload/inverse builders per op type + undo inversion (§5.7)
  bus.py         Redis pub/sub fan-out + ephemeral presence hash (§5.8)
  hub.py         per-instance WS session registry, subscribes per active project
  fracindex.py   LexoRank-style fractional ordering keys
  schema.py      idempotent DDL bootstrap (§5.1)
  config.py      env-driven settings
  static/index.html   self-contained browser demo client (served at /)
tests/
  test_convergence.py   multi-client cross-instance convergence + reconnect (needs stack)
  test_fracindex.py     fractional indexing unit tests (standalone)
  client.py             minimal WS protocol test client
docker-compose.yml  postgres, redis, app1, app2, nginx
Dockerfile          app image (python 3.12-slim, uvicorn[uvloop])
nginx.conf          L7 LB with WS upgrade, ip_hash sticky-by-connection
```
