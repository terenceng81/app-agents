# Agent Rules — app-agents

## Signal strings — never change these

These exact strings are parsed by regex in `deploy-app.py` and `build-app.sh`:

| String | Meaning |
|---|---|
| `-- NO_DATABASE_NEEDED` | PATH A — no Neon, no auth |
| `REPO_SLUG: kebab-name` | App slug used for repo name + domain |
| `-- NO_MIGRATION_NEEDED` | Update requires no DB change |
| `-- NO_FIXES_NEEDED` | QA reviewer found no bugs |

If you change the format in `finalize-app.yaml`, update the matching regex in `deploy-app.py` too.

## PATH A vs PATH B

`db_architect` in `finalize-app.yaml` outputs one of two signals.
Every downstream step (frontend_coder, qa_reviewer, deploy-app.py) reads this signal.
Never assume one path — always trace the db_architect output.

## ao roles are in the npm package

The 199 agent roles are bundled inside `agency-orchestrator` npm package (`agency-agents-zh`).
They are NOT in this repo. Do not create local `agency-agents/` folders unless overriding specific roles.

## build-app.sh is the source of truth

All pipeline modes (create/update/delete) go through `build-app.sh`.
`app-builder-api.py` is a thin HTTP wrapper around the same script — do not duplicate logic there.

## templates/ are injected verbatim

Files in `skills/app-builder/templates/` are injected directly by `frontend_coder`.
If you change a template, the change affects every new app built after that.
