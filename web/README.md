# Sonata — Collaborative Subtitles (Web)

Next.js (App Router) + TypeScript + Tailwind client for the real-time collaborative
subtitles backend, plus a Playwright suite that spawns two user views across two distinct
backend instances and asserts cross-instance convergence.

## Design

A clean, editorial light theme tuned for a dubbing studio:

- **Type** — Fraunces (serif display/wordmark), Hanken Grotesk (UI), IBM Plex Mono
  (timecodes, ids, sequence numbers), loaded at runtime so the build stays offline-safe.
- **Palette** — warm paper canvas, near-black ink, hairline rules, an emerald accent,
  amber "live", and per-speaker colors.
- **Editor** — sticky top bar (wordmark, instance badge, pulsing live pill, overlapping
  presence avatars, "Open on app2 ↗"), a studio-style timeline table with row numbers,
  mono timecodes + a formatted `mm:ss.cc` readout, speaker color dots, hover reorder/delete,
  and a live activity feed. Peer cursors render as a colored border + a floating name tag on
  the exact field a peer is editing.

## Run with the stack (recommended)

This client is part of the root `docker-compose.yml`, so the whole app comes up together:

```bash
# from the repo root
docker compose up -d --build      # backend + this client → http://localhost:3000
```

(If port 3000 is busy, use `WEB_PORT=3001 docker compose up -d --build`.)

## Run standalone (hot reload)

The backend must be running (FastAPI + Postgres + Redis + nginx via docker compose from the
repo root). Then:

```bash
cd web
npm install
npx playwright install chromium   # for the simulations (one-time)

npm run dev      # dev server (default Next port 3000)
npm run build    # production build (strict TS)
```

**Cross-instance demo:** create a project, then use the **“Open on app2 ↗”** link in the
header to open the same project on the other instance. Each tab is a different user on a
different backend instance; edits converge live. Pick the instance per tab with
`?instance=app1|app2|lb` (the landing page also has a selector).

## Environment

Defaults are baked in; override via `.env.local` (see `.env.local.example`):

```
NEXT_PUBLIC_APP1_HTTP=http://localhost:8001
NEXT_PUBLIC_APP2_HTTP=http://localhost:8002
NEXT_PUBLIC_LB_HTTP=http://localhost:8080
```

`wsBase` is derived from each by swapping `http` → `ws`.

## Tests

```bash
npm test                                    # == npx playwright test (10 simulations)
PW_SLOWMO=700 npx playwright test --headed  # watch them run in real browser windows
PW_VIDEO=1 npx playwright test              # record per-user videos to test-results/pairs/
```

Playwright builds and starts the app on **port 3100** (via its `webServer`); set
`PW_PORT=<port>` to change it (3100 avoids a 3000 that may be taken on the dev machine).
The suite represents two users in two browser contexts: **User A connects through app1,
User B through app2**, so every assertion exercises genuine cross-instance convergence.

## Simulation gallery

Each clip is a **single side-by-side recording of both users**: the **left pane (teal bar)
is User A on `app1`**, the **right pane (indigo bar) is User B on `app2`**. They were
produced by `PW_VIDEO=1 npx playwright test` (per-user `.webm`) and merged with `ffmpeg`
(`scripts/merge-videos.sh`).

| # | Scenario | What it proves | Video |
|---|----------|----------------|-------|
| 1 | Create + type | A line created and typed on app1 appears on app2 | [▶](../docs/media/playwright/1-create-type-text-converges-a-app1-b-app2.mp4) |
| 2 | Same-text LWW | Concurrent edits to the same text converge to one value | [▶](../docs/media/playwright/2-concurrent-edits-to-same-text-converge-to-one-value-lww.mp4) |
| 2b | Same field + live cursors | Both users in one field see each other's cursor, then converge | [▶](../docs/media/playwright/2b-two-users-in-the-same-field-live-peer-cursors-render-then-converge.mp4) |
| 3 | Different fields | Concurrent edits to different fields both survive | [▶](../docs/media/playwright/3-concurrent-edits-to-different-fields-both-survive.mp4) |
| 4 | Reorder | Reordering rows converges to one identical order | [▶](../docs/media/playwright/4-add-3-reorder-converges-row-order.mp4) |
| 5 | Delete | Deleting a line removes it for the peer | [▶](../docs/media/playwright/5-delete-removes-segment-for-the-peer.mp4) |
| 6 | Undo | Undo reverts an edit visibly to the peer | [▶](../docs/media/playwright/6-undo-reverts-an-edit-visibly-to-the-peer.mp4) |
| 7 | Presence | A presence avatar appears when a peer focuses a field | [▶](../docs/media/playwright/7-presence-chip-appears-for-a-focused-peer.mp4) |
| 8 | Reconnect / reload | Reloading a peer resyncs it to the converged state | [▶](../docs/media/playwright/8-reload-b-resyncs-to-converged-state.mp4) |
| 9 | Randomized stress | 30 mixed ops from both users converge and match the backend DB | [▶](../docs/media/playwright/9-randomized-stress-simulation-converges-and-matches-backend.mp4) |

Regenerate: `PW_VIDEO=1 npx playwright test && ./scripts/merge-videos.sh`.

## Routes

- `/` — instance selector, create-project, join-existing.
- `/p/[projectId]?instance=app1|app2|lb` — editor (defaults to `lb`).

## Architecture

- `lib/useCollab.ts` — the WebSocket/protocol hook. Maintains a `Map<chunk_id, Segment>`,
  orders rows by `(position ASC, chunk_id ASC)`, tracks `observedSeq` and unacked ops, and
  reconnects with `hello { last_seq }` + idempotent replay of unacked ops.
- `lib/api.ts` — REST client (`POST /projects`, `GET /projects/{id}`, `GET /health`).
- `lib/config.ts` — instance → base URL mapping, the fixed speaker set + colors, peer colors.
- `lib/format.ts` — timecode + avatar-initials helpers.
- `app/p/[projectId]/` — editor page, `Editor` (header/toolbar/table/activity), `SegmentRow`.

State is server-authoritative: committed ops drive rendering. The only local optimism is
keeping a focused input smooth so remote echoes never clobber the caret.

## Convergence semantics mirrored from the backend

- `create` / `update` / `delete` / `move` op payloads applied exactly as the server emits them.
- `move` sends neighbor **position strings** as `before`/`after`; the server mints the fractional key.
- Per-field last-writer-wins; rows tie-break on `chunk_id` after `position`.
