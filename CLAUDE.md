# app-agents — Claude Code Context

## What is this?

The Mac-local, `ao` CLI version of the Hermes App Builder pipeline.
Files here are deployed into `~/.hermes/` on the Mac and run by the Hermes agent.

The TypeScript/Vercel version lives in [`app-studio`](https://github.com/terenceng81/app-studio).

## How files map to ~/.hermes/

```
skills/app-builder/  →  ~/.hermes/skills/app-builder/
scripts/             →  ~/.hermes/scripts/
workflows/           →  ~/.hermes/workflows/
```

## Pipeline — 3 stages

**Stage 1** (`ao compose`)
`ao` reads all 199 roles from `agency-agents-zh` (bundled in the npm package).
Claude dynamically picks 4–6 relevant experts and generates a workflow YAML.

**Stage 2** (`ao run workflows/finalize-app.yaml`)
Three sequential agents: `db_architect` (PATH A/B decision + REPO_SLUG + schema.sql),
`frontend_coder` (full file tree), `qa_reviewer` (deployment bug check).

**Stage 3** (`scripts/deploy-app.py`)
Neon DB creation → GitHub repo → Vercel deploy + env vars → Cloudflare CNAME → screenshot.

## Rules

- **Do not modify `workflows/finalize-app.yaml` agent prompts** without testing — the PATH A/B signal strings and REPO_SLUG format are parsed by regex in deploy-app.py.
- **`build-app.sh` is the single entry point** — all modes (create/update/delete) go through it.
- **`ao` must be installed globally** — `npm install -g agency-orchestrator`. Verify with `ao --version`.
- **Signal strings are exact** — `-- NO_DATABASE_NEEDED`, `REPO_SLUG: slug-here`, `-- NO_MIGRATION_NEEDED`. Do not alter.

## Required env keys

All keys must be in `~/.hermes/.env`. See `.env.example`.

## Testing a change

```bash
# Run create mode directly (bypasses Hermes/Telegram)
bash ~/.hermes/scripts/build-app.sh create --description "a simple calculator"

# Resume a failed deploy (skips Neon/GitHub, redo Vercel only)
python3 ~/.hermes/scripts/finish-vercel.py --repo app-tg123-calculator
```
