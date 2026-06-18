# app-agents — Hermes App Builder Pipeline (Mac / ao CLI version)

Original Mac-local pipeline that generates and deploys full-stack Next.js 14 apps from a single Telegram message.
The TypeScript/Vercel-ready version lives in [`app-studio`](https://github.com/terenceng81/app-studio).

## Architecture

```
Trigger (Telegram / Hermes agent)
  └── skills/app-builder/SKILL.md   ← intent detection (CREATE / UPDATE / DELETE)
        └── scripts/build-app.sh   ← pipeline orchestrator
              ├── Stage 1: ao compose                         ← dynamic 4-6 expert team from 199 roles
              ├── Stage 2: ao run workflows/finalize-app.yaml ← db_architect → frontend_coder → qa_reviewer
              └── Stage 3: scripts/deploy-app.py              ← Neon + GitHub + Vercel + Cloudflare
```

## Contents

| Path | Purpose |
|---|---|
| `skills/app-builder/SKILL.md` | Hermes skill — detects CREATE/UPDATE/DELETE intent |
| `scripts/build-app.sh` | Main orchestrator — create, update, delete modes |
| `scripts/deploy-app.py` | Stage 3 — Neon DB, GitHub repo, Vercel deploy, Cloudflare CNAME |
| `scripts/finish-vercel.py` | Resume a half-done deploy (skips Neon/GitHub, just Vercel) |
| `scripts/app-builder-api.py` | FastAPI build API (port 8788) — for Northflank/cloud hosting |
| `workflows/finalize-app.yaml` | ao workflow: db_architect → frontend_coder → qa_reviewer |
| `workflows/update-app.yaml` | ao workflow for update mode |
| `skills/app-builder/templates/` | Next.js boilerplate files injected at build time |
| `skills/app-builder/references/` | Recovery patterns and debugging guides |

## PATH A vs PATH B

The `db_architect` agent decides:
- **PATH A** — no database needed (calculators, tools). 3 files, no auth, no Neon.
- **PATH B** — full stack (Better Auth + Neon Postgres). 12 files including middleware, lib/auth.js, Server Actions.

## Dependencies

### agency-orchestrator (ao)

Stages 1 and 2 use `ao` — a multi-agent workflow engine with 199 built-in AI roles bundled in the npm package.

```bash
npm install -g agency-orchestrator
ao --version    # verify install
ao roles        # should list 199 roles
```

### Python dependencies (Stage 3)

```bash
pip3 install requests neon-api Pillow
```

### Other

- `hermes` CLI — AI agent runtime
- `gh` CLI — GitHub repo creation

## Setup on a new machine

```bash
# 1. Copy files into ~/.hermes/ (hermes must already be installed)
git clone git@github.com:terenceng81/app-agents.git /tmp/app-agents
cp -r /tmp/app-agents/scripts ~/.hermes/
cp -r /tmp/app-agents/skills ~/.hermes/
cp -r /tmp/app-agents/workflows ~/.hermes/

# 2. Fill in env keys
cp .env.example ~/.hermes/.env    # then edit with your keys

# 3. Install ao
npm install -g agency-orchestrator
```

## Required .env keys

See `.env.example` for the full list with comments.

## Relationship to app-studio

[`app-studio`](https://github.com/terenceng81/app-studio) is a TypeScript rewrite of this pipeline embedded inside a Next.js app — no ao CLI, no Python, no bash. It is Vercel-compatible. This repo is the Mac-local reference implementation.
