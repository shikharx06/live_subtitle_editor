# 🎬 Sonata — Real-Time Collaborative Subtitles Editor

> Multiple people edit one subtitle timeline at the same time — think Google Docs for a
> dubbing studio. Every edit appears live and ends up identical for everyone, even when
> they're connected to different servers.

A project is an ordered list of **segments** (`chunk_id, start_time, end_time, speaker_id,
text`). Editors create, edit, delete, and reorder them together; the document survives
restarts, and reconnecting never loses or duplicates edits. Designed for 2–20 editors per
project, thousands of projects, across many servers behind a load balancer, with edits
echoed in **under 150 ms**.

---

## Table of contents

- [Demo](#demo)
- [Features](#features)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Web client](#web-client)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Design document](#design-document)

---

## Demo

Two users editing the same project on **two different servers** — left = `app1`, right =
`app2`. Watch the edits converge live. These are the Playwright simulations:

```bash
cd web
npx playwright test                        # 10 two-user cross-instance simulations
PW_SLOWMO=700 npx playwright test --headed # watch them run; PW_VIDEO=1 records the clips
```

https://github.com/user-attachments/assets/45db4f6e-a9ea-4deb-9d62-c8b6a503ff6e

<details>
<summary><b>More demos</b> — same-text edits, same-field cursors, reorder, delete, undo, presence, reconnect, stress test</summary>

https://github.com/user-attachments/assets/2752ba49-7d88-40bb-8bd7-ea68b3644b20

https://github.com/user-attachments/assets/30e0b17e-dee8-4f52-a248-1b66b5821865

https://github.com/user-attachments/assets/1ccf34c5-d45c-4f13-a575-f80ea9a2876f

https://github.com/user-attachments/assets/9ec7657b-7184-4518-83d0-bd1a51c5ade1

https://github.com/user-attachments/assets/e5a8b019-de87-475e-89f5-f5613c1e7301

https://github.com/user-attachments/assets/71baf287-3e36-4019-85d6-9ff4f0459ec6

https://github.com/user-attachments/assets/5f402664-35a4-4166-8afe-2296d546b904

https://github.com/user-attachments/assets/0ef2dee5-8474-47c2-9e5e-6184090587f4

https://github.com/user-attachments/assets/c352f057-59d0-420a-a56a-784a11cd5ca3

</details>

---

## Features

- **Edit together live** — create, edit, delete, and reorder segments; everyone sees changes instantly.
- **Always converges** — editors on different servers end up in the exact same state.
- **Presence** — see who's online and which field each person is editing.
- **Survives restarts** — the document is saved; reconnect and you're caught up.
- **Undo + history** — per-user undo and a log of who changed what.
- **No lost edits** — dropped connections never lose or duplicate your work.
- **Scales out** — stateless servers behind a load balancer.

---

## How it works

![Architecture](docs/architecture.svg)

- Clients connect over **WebSocket** through a load balancer to any of several identical,
  stateless **FastAPI** servers.
- Every edit is saved to **PostgreSQL**, which stamps it with a per-project version number.
  That ordering is what makes everyone converge — replay the edits in order and you always
  get the same result.
- **Redis** broadcasts each saved edit to the other servers (so users on different servers
  stay in sync) and holds live presence.

If Redis goes down, clients simply re-sync from PostgreSQL — the document is never at risk.
The data model, edit-conflict rules, scaling limits, and failure handling are explained in
[`DESIGN.md`](./DESIGN.md).

---

## Tech stack

Python 3.12 · FastAPI + WebSocket · PostgreSQL · Redis · nginx · Next.js + TypeScript +
Tailwind (web client) · Playwright (tests) · Docker Compose.

---

## Quick start

One command brings up the whole stack — database, cache, two app servers, load balancer,
and the web client:

```bash
docker compose up -d --build     # postgres, redis, app1, app2, nginx, web
docker compose ps                # wait until everything is healthy
```

- **Editor (web UI):** http://localhost:3000
- **Backend API:** http://localhost:8080 (load balancer), or :8001 / :8002 (the two servers directly)

If port 3000 is taken, pick another: `WEB_PORT=3001 docker compose up -d --build`. Tear down
with `docker compose down -v`.

---

## Web client

The Next.js editor comes up with the stack above at **http://localhost:3000**. Create a
project, then click **“Open on app2 ↗”** to open the same project on the other server in a
second tab — edit in either and watch them sync.

For frontend development with hot reload, run it outside Docker instead:

```bash
cd web && npm install && npm run dev
```

More in [`web/README.md`](web/README.md).

---

## Testing

```bash
# backend tests (stack must be running)
uv venv .venv && uv pip install -r requirements.txt pytest pytest-asyncio websockets
.venv/bin/python -m pytest tests/ -v
```

Browser simulations (two users on two servers running every operation) are under [Demo](#demo).

---

## Project structure

```
app/      FastAPI backend — api / services / domain / persistence / realtime layers
tests/    backend convergence tests
web/      Next.js client + Playwright simulations
docs/     architecture diagram + demo videos
DESIGN.md full design doc
```

---

## Design document

[`DESIGN.md`](./DESIGN.md) has the complete design: requirements, sizing estimates,
architecture, data model, edit-conflict rules, 8 decision records (ADRs), scaling limits,
and failure handling.
