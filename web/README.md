# Collaborative Subtitles Editor — Web

Next.js (App Router) + TypeScript + Tailwind frontend for the real-time collaborative
subtitles backend, plus a Playwright suite that spawns two user views across two distinct
backend instances and asserts cross-instance convergence.

## Prerequisites

The backend must be running (FastAPI + Postgres + Redis + nginx via docker compose):

```bash
# from the repo root
docker compose up -d --build
```

Verify: `curl http://localhost:8001/health` should return `{"status":"ok","instance":"app1"}`.
The suite checks app1 and app2 health in `globalSetup` and fails fast with instructions if either is down.

## Setup

```bash
cd web
npm install
npx playwright install chromium
```

## Environment

Defaults are baked in; override via `.env.local` if needed (see `.env.local.example`):

```
NEXT_PUBLIC_APP1_HTTP=http://localhost:8001
NEXT_PUBLIC_APP2_HTTP=http://localhost:8002
NEXT_PUBLIC_LB_HTTP=http://localhost:8080
```

`wsBase` is derived from each by swapping `http` -> `ws`.

## Run

```bash
npm run dev      # dev server (default Next port 3000)
npm run build    # production build (strict TS)
```

## Test

```bash
npm test         # == npx playwright test
```

Playwright builds and starts the app on **port 3100** (via its `webServer`) and manages
that server's lifecycle. Port 3100 is used instead of 3000 because another unrelated dev
server may occupy 3000 on the dev machine; override with `PW_PORT=<port>` if desired.
The suite represents two users in two browser contexts: **User A connects through app1,
User B through app2**, so every assertion exercises genuine cross-instance convergence.

## Routes

- `/` — instance selector, create-project, join-existing.
- `/p/[projectId]?instance=app1|app2|lb` — editor (defaults to `lb`).

## Architecture

- `lib/useCollab.ts` — the WebSocket/protocol hook. Maintains a `Map<chunk_id, Segment>`,
  orders rows by `(position ASC, chunk_id ASC)`, tracks `observedSeq` and unacked ops,
  and reconnects with `hello { last_seq }` + idempotent replay of unacked ops.
- `lib/api.ts` — REST client (`POST /projects`, `GET /projects/{id}`, `GET /health`).
- `lib/config.ts` — instance -> base URL mapping, the fixed speaker UUID set, peer colors.
- `app/p/[projectId]/` — editor page, `Editor` (header/toolbar/table/activity), `SegmentRow`.

State is server-authoritative: committed ops drive rendering. The only local optimism is
keeping a focused input smooth so remote echoes never clobber the caret.

## Convergence semantics mirrored from the backend

- `create` / `update` / `delete` / `move` op payloads applied exactly as the server emits them.
- `move` sends neighbor **position strings** as `before`/`after`; the server mints the fractional key.
- Per-field last-writer-wins; rows tie-break on `chunk_id` after `position`.
