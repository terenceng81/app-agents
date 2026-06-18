# app-agent — Hermes App Builder Pipeline

Full-stack Next.js app generation pipeline triggered by Telegram (via Hermes AI agent) or the App Builder Studio.

## Architecture

```
Trigger (Telegram / Studio)
  └── skills/app-builder/SKILL.md   ← intent detection
        └── scripts/build-app.sh   ← pipeline orchestrator
              ├── Stage 1: ao compose           ← design expert team
              ├── Stage 2: ao run finalize-app.yaml  ← db + code + QA
              └── Stage 3: scripts/deploy-app.py     ← Neon + GitHub + Vercel + Cloudflare
```

## Contents

| Path | Purpose |
|---|---|
| `skills/app-builder/SKILL.md` | Hermes skill — detects CREATE/UPDATE/DELETE intent |
| `scripts/build-app.sh` | Main orchestrator — `create`, `update`, `delete` modes |
| `scripts/deploy-app.py` | Stage 3 — Neon DB, GitHub repo, Vercel deploy, Cloudflare CNAME |
| `scripts/finish-vercel.py` | Resume a half-done deploy (skips Neon/GitHub, just Vercel) |
| `scripts/app-builder-api.py` | FastAPI build API (port 8788) — used when running on Northflank |
| `workflows/finalize-app.yaml` | ao workflow: db_architect → frontend_coder → qa_reviewer |
| `workflows/update-app.yaml` | ao workflow for update mode |
| `skills/app-builder/templates/` | Next.js boilerplate files injected at build time |
| `skills/app-builder/references/` | Recovery patterns and debugging guides |

## Build Modes

### PATH A — No database
Pure tools/calculators. 3 files, no auth, no Neon.

### PATH B — Full stack
Better Auth + Neon Postgres. 12 files including middleware, lib/auth.js, Server Actions.

The `db_architect` agent in `finalize-app.yaml` decides which path based on the app description.

## Dependencies

### agency-orchestrator (`ao`)

The pipeline uses `ao` — a multi-agent workflow engine with 199 built-in AI roles. The roles (db_architect, frontend_coder, qa_reviewer, product-manager, etc.) are **bundled inside the npm package** — they are not in this repo.

Install on a new machine:

```bash
npm install -g agency-orchestrator
ao init --lang en    # optional: pre-cache English role definitions
```

Verify: `ao --version` and `ao roles` should list 199 roles.

The workflows reference `agents_dir: "agency-agents"`. When no local `agency-agents/` folder exists (the default), `ao` falls back to its bundled `agency-agents-zh` library automatically.

### Other dependencies

- `hermes` CLI — the AI agent runtime (provides `ao` indirectly via Hermes install)
- `python3` with `requests`, `neon-api`, `Pillow` (for `deploy-app.py`)
- `gh` CLI — GitHub repo creation

## Required .env Keys

```
GITHUB_TOKEN=
VERCEL_TOKEN=
NEON_API_KEY=
GITHUB_OWNER=
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_ZONE_ID=
CUSTOM_DOMAIN_BASE=nhkclouds.com
```

## Studio Integration

[App Builder Studio](https://github.com/terenceng81/app-studio) calls `build-app.sh` directly via Node.js `child_process.spawn` — no intermediary API needed when running locally.

For cloud deployment (Northflank), `app-builder-api.py` (FastAPI) wraps the same scripts behind an authenticated HTTP API that the Studio proxies to.
