# MEMORY.md — Institutional Knowledge for AI Coders

## Why the pipeline has 3 stages (not 2)

Stage 1 (`ao compose`) is a meta-step — Claude picks the right experts dynamically.
Stage 2 (`ao run finalize-app.yaml`) is fixed — always the same 3 agents.
Stage 3 (`deploy-app.py`) is infra-only — no LLM calls, pure API automation.

This separation means you can re-run any stage independently without touching the others.

## Why ao compose uses dynamic expert selection

The 199 roles in `agency-agents-zh` cover domains like product, UX, engineering, legal, marketing.
A recipe app needs different experts than a fintech dashboard. Hardcoding roles would produce
generic output. `ao compose` reads the full catalog and asks Claude to pick 4-6 relevant ones.

## Why deploy-app.py uses Python (not bash)

The deployment flow has complex branching (PATH A vs B), error handling, and multiple API calls
with JSON parsing. Python's `requests` library and exception handling are much cleaner than bash
for this. The Pillow dependency handles the post-deploy screenshot.

## Better Auth SSR crash — frontend_coder template fix

PATH B apps crash during Next.js SSR because `better-auth`'s React client accesses `window` at
module init time. The only fix is wrapping every page that uses `authClient` with:
```js
import dynamic from 'next/dynamic'
const Page = dynamic(() => import('./_client'), { ssr: false, loading: () => null })
```
The templates in `skills/app-builder/templates/` enforce this. The qa_reviewer agent in
`finalize-app.yaml` also checks for this bug.

## Why finish-vercel.py exists

Long-running deploys occasionally fail at the Vercel step after Neon and GitHub succeed.
Re-running `build-app.sh` would create duplicate Neon DBs and GitHub repos. `finish-vercel.py`
skips those steps and only retries Vercel + Cloudflare, using the existing repo.

## app-builder-api.py — when to use it

Only needed when the pipeline runs on a remote server (Northflank, Railway) and the Studio
needs to call it over HTTP. For local Mac use, Studio calls `build-app.sh` directly. The API
is a thin wrapper — all logic stays in `build-app.sh`.

## Relationship to app-studio

`app-studio` (`github.com/terenceng81/app-studio`) is a TypeScript rewrite of this entire
pipeline embedded inside a Next.js 16 app. It replaced:
- `ao compose` → `composeWorkflow()` from agency-orchestrator SDK
- `ao run finalize-app.yaml` → direct Anthropic SDK calls
- `deploy-app.py` → `lib/deploy.ts` using fetch() + GitHub Tree API

The prompts in `finalize-app.yaml` are the source of truth — `app-studio/lib/ai-pipeline.ts`
uses verbatim copies of those prompts. If you improve a prompt here, port it to app-studio too.

## .env key NEON_REGION

Default is `aws-ap-southeast-1` (Singapore). Change this if deploying from a different region
to reduce Neon database latency. The region is set once at DB creation and cannot be changed.
