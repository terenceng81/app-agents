---
name: app-builder
description: "Build and update web apps from chat messages. Creates full-stack Next.js 14 apps with Better Auth + Neon Postgres, deployed to Vercel via GitHub. Triggered by phrases like 'build me an app', 'create a web app', 'make me a tool', 'update my app', 'add a feature to my app', 'change my app'."
version: 2.3.0
author: Terence
platforms: [macos]
metadata:
  hermes:
    tags: [app-builder, telegram, github, vercel, neon, deployment]
---

# App Builder Skill

Build and deploy full-stack Next.js 14 apps automatically via one shell command.

## Detect Intent

**CREATE** — the user wants a new app:
- "build me an app / web app / tool"
- "make me a [feature] app / website"
- "I want a web app that [does X]"
- "deploy an app"
- "create a web application for [purpose]"

**UPDATE** — the user wants to change an existing app:
- "add [feature] to my app"
- "update / change / tweak my app"
- "modify the UI of my app"

**CRITICAL**: Never write code directly. Always run the bash script below. No exceptions.

---

## CREATE: Run This Exact Command

When the user wants to CREATE a new app, extract their Telegram user ID and run ONE command:

```bash
bash ~/.hermes/scripts/build-app.sh create "TELEGRAM_USER_ID" "TELEGRAM_USERNAME" "USER_DESCRIPTION"
```

Example:
```bash
bash ~/.hermes/scripts/build-app.sh create "8724348754" "terence" "Build a budget tracker app with login, income/expense categories, and a monthly overview"
```

**Tell the user first:** "⏳ Generating and deploying — this takes about 5–10 minutes, please hold on…"

Then run the command and wait for it to finish. It prints a live URL at the end.

When done, parse the script output for these keys:
- `CUSTOM_URL:` — preferred public URL (custom domain). Use this if present.
- `URL:` — Vercel deployment URL (fallback if no CUSTOM_URL).
- `REPO:` — GitHub repo URL.
- `SCREENSHOT:` — local path to a PNG screenshot of the live app. If present, send the image.

Reply with:
```
✅ Your app is live!

🔗 [CUSTOM_URL if present, else URL]
📦 GitHub: [REPO from output]

[If PATH B (has database): "Sign up with an email to start; your data syncs to the cloud."]
Want to change a feature or the look? Just tell me!
```

If SCREENSHOT path is present, send the image file as a media message alongside the text.

## Post-Deploy Verification (MANDATORY)

After `build-app.sh` finishes, run these checks BEFORE telling the user the app is live:

1. **Verify env vars:**
   ```bash
   cd /tmp/<repo-name> && vercel link --repo --yes && vercel env ls
   ```
   Must show BOTH `DATABASE_URL` AND `BETTER_AUTH_SECRET`. If either is missing, add it:
   ```bash
   echo "$(openssl rand -base64 32)" | vercel env add BETTER_AUTH_SECRET production
   ```

2. **Verify auth endpoints work:**
   ```bash
   curl -s -o /dev/null -w "sign-up: HTTP %{http_code}\n" \
     -X POST "https://<url>/api/auth/sign-up/email" \
     -H "Content-Type: application/json" \
     -d '{"email":"verify@test.com","password":"verify123","name":"Verify"}'
   # Must return HTTP 200, NOT 500
   ```

3. **If sign-up returns 500:** check the cookie name in `middleware.js`:
   ```bash
   grep "session_token" middleware.js
   ```
   It must check BOTH `__Secure-better-auth.session_token` AND `better-auth.session_token`.

4. **If build warned about baseURL:** add `BETTER_AUTH_URL` env var and update
   `lib/auth.js` to include `baseURL` config.

---

## UPDATE: Run This Exact Command

First, find the user's repo:
```bash
gh repo list terenceng81 --json name --jq '.[].name' | grep "^app-tg"
```

If there is only one repo, use it. If multiple, ask the user which app to update.

Then run:
```bash
bash ~/.hermes/scripts/build-app.sh update "TELEGRAM_USER_ID" "REPO_NAME" "UPDATE_REQUEST"
```

Example:
```bash
bash ~/.hermes/scripts/build-app.sh update "8724348754" "app-tg8724348754-budget-tracker" "Add a dark mode toggle"
```

When done, reply with:
```
✅ Update complete! Same URL: [same URL]
Changed: [what was updated]
```

---

## DELETE: Run This Exact Command

When the user wants to DELETE / remove / tear down an existing app:

First, find the repo name:
```bash
gh repo list terenceng81 --json name --jq '.[].name' | grep "^app-tg"
```

If multiple repos exist, ask the user which one to delete. If only one, confirm before proceeding.

Then run:
```bash
bash ~/.hermes/scripts/build-app.sh delete "REPO_NAME"
```

Example:
```bash
bash ~/.hermes/scripts/build-app.sh delete "app-tg8724348754-expense-tracker"
```

This deletes: **Neon project** + **Vercel project** + **GitHub repo** + removes from registry.

When done, reply with:
```
🗑️ Deleted:
- GitHub: github.com/terenceng81/[repo-name] ✓
- Vercel: [repo-name].vercel.app ✓
- Neon database ✓
```

---

See `references/recovery-patterns.md` for concrete transcripts of recovering from timeouts,
session limits, and failed fallback providers.

## Important Rules

1. **ALWAYS run the bash command** — never write app code in the conversation.
2. **Wait for the command to finish** — it takes 3–5 minutes.
3. **The URL comes from the script output** — do not make up URLs.
4. If the script errors, show the error message to the user and ask how to proceed.
4. If the script errors, show the error message to the user and ask how to proceed.
The build engine defaults to `claude-code` (best quality). To force the local model instead,
append `"hermes-cli"` as a 4th argument. **WARNING: `hermes-cli` produces empty code output
for the finalize step — do not use it. Only `claude-code` generates usable apps.**

---

## Pitfalls & Recovery

### Timeout: 600s is tight for the full pipeline
The 3-stage pipeline (compose → finalize → deploy) often exceeds 600s, especially for
complex app descriptions. Stages 1 and 3 are fast (~3 min each); Stage 2 (finalize) is
the bottleneck because `claude-code` generates the entire Next.js codebase in one pass.

**Set user expectations honestly:** "This takes 5–10 minutes" not "3–5 minutes."

### Stage 2 (finalize) times out — most common failure mode
When the script output ends with `[Stage 2] … 📡 Received …` and then 600s elapses,
the finalize step didn't finish. The claude-code child process may still be running.
Check with:

```bash
ps aux | grep claude | grep -v grep | grep "resume"
```

**If you see a claude-code process with 3+ minutes of CPU time and still running:** let it
complete. Poll every 60s with `ls -lt ~/.hermes/ao-output/App\ Builder\ -\ Finalize-* | head -1`
until a new Finalize dir appears. Then run Stage 3 manually (see Stage 3 recovery below).

**If CPU time is frozen (stuck at same value for 2+ minutes):** the process hung. Kill it
(`kill <PID>`) and restart the build. The compose spec from Stage 1 is preserved.
**Do NOT retry more than 2 restarts** — Claude Code has session limits (see below).

### Stage 3 (deployment) times out — recoverable
Stage 2 (code generation) and the GitHub push usually completed fine. To finish:

1. **Confirm the repo exists:**
   ```bash
   gh repo view "terenceng81/app-tg<TG_ID>-<slug>" --json name,url
   ```

2. **Find the FINAL_DIR** (most recent Finalize dir):
   ```bash
   ls -dt ~/.hermes/ao-output/"App Builder — Finalize-"-*/ | head -1
   ```

3. **Run the deploy step manually:**
   ```bash
   python3 ~/.hermes/scripts/deploy-app.py \
       --mode create \
       --ao-output "<FINAL_DIR>" \
       --repo-name "app-tg<TG_ID>-<slug>" \
       --tg-user-id "<TG_ID>"
   ```

4. **Get the live Vercel URL:**
   ```bash
   vercel list 2>/dev/null | grep "<REPO_NAME>" | head -1
   ```

Even if deploy-app.py reports "Timeout waiting for deployment", the app usually finishes
deploying moments later — just re-check with `vercel list` or curl the URL.

### Claude Code session limit
Claude Code has an hourly session token limit (resets at the top of the next hour).
If the compose or finalize step fails with:
```
You've hit your session limit · resets <time> (Asia/Singapore)
```
**Stop immediately.** All retries will fail until the reset time. Tell the user when the
reset happens and offer to schedule a retry. Do not keep restarting — it wastes tokens
and frustrates the user.

### hermes-cli produces empty apps
Do not use `hermes-cli` as a fallback provider. It completes in ~11 seconds but generates
zero code files (`metadata.json` is ~1KB vs ~36KB for claude-code). The deploy step then
fails with "No code files found in ao output." Only `claude-code` produces working apps.

### Schema mismatch — db_architect output differs from compose design

**Symptom:** After manually writing API routes based on the compose team's design plan,
the app deploys but API calls fail because tables/columns don't exist.

**Root cause:** The `db_architect` step generates its OWN schema that may differ
significantly from the compose team's design. Common differences:
- Table names: `class_sessions` instead of `classes`, `locations` instead of `studio_locations`
- Column names: `starts_at` instead of `start_time`, `owner_id` instead of `user_id`
- Missing columns: no `difficulty` on class_types, no `confirmed_count` on sessions
- Different FK names: `session_id` instead of `class_id` on bookings

**Detection — after schema is applied, before writing API routes:**
```bash
# List all tables
psql -c "\dt"
# Inspect column names per table
psql -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='bookings' ORDER BY ordinal_position"
```

**Recovery:** Rewrite ALL API routes and frontend data accesses to match the actual
schema from `1-db_architect.md`, NOT the compose design plan. Run `\dt` and column
inspection on the deployed Neon DB before writing any query.

### Line number corruption — read_file output poisons write_file

**Symptom:** After using `read_file` + `write_file` in execute_code, the file on disk
has `1|`, `2|` prefixes on every line, causing JavaScript syntax errors.

**Root cause:** `read_file` returns content with line number prefixes (`1|'use client'`).
Using `write_file` with that content writes the line numbers into the actual file.

**Detection:**
```bash
head -3 <file>
# If lines start with "1|", "2|", the file is corrupted
```

**Recovery:** Revert corrupted files with `git checkout` and use `sed` or `patch`
for text replacements instead of read_file → replace → write_file.

**DO:** `sed -i '' 's/start_time/starts_at/g' file.js`
**DON'T:** `content = read_file(f); content = content.replace(...); write_file(f, content)`

### Session limit recovery — write code manually

When Claude Code hits session limit (`resets <time>`), the user may say "try again now."
Do NOT retry — explain clearly that the limit won't reset until the stated time, then
offer the manual path immediately:

> Can't retry — session limit won't reset until `<time>`. Let me take the manual approach
> instead. I have the design plan and schema ready. I'll write the full app code now.

This is the fastest path. After two manual builds (Health Pulse + Yoga Schedule),
the proven workflow is:
1. Run compose to get design plan (even if Stage 2 fails, the terminal output has the plan)
2. Run finalize to get db_architect schema (even if frontend_coder fails)
3. Create GitHub repo via `gh repo create`
4. Write all boilerplate + app code manually
5. Create Neon project + run schema via psql
6. Set up Vercel + env vars via API
7. Deploy via `vercel --prod --yes`

### Neon API — no /sql endpoint; use psql

The Neon v2 API has NO `/projects/{id}/sql` endpoint (returns 404).
To run schema SQL, install PostgreSQL client:
```bash
brew install libpq
```
Then connect via psql with the connection URI. Parse the URI to extract host/user/password.
Set `PGPASSWORD` env var and use `sslmode=require` for TLS.

### Vercel deployment protection — must disable

After creating a Vercel project, deployment protection (SSO) is enabled by default,
showing a Vercel auth page instead of the app. Disable it via API:
```python
PATCH /v9/projects/{repo_name}
Body: {"ssoProtection": null, "trustedIps": null}
```
Then redeploy with `vercel --prod --yes` for the change to take effect.

### Seed data — app needs baseline data to function

After schema is applied, the app needs seed data (class types, locations, instructors)
before class sessions can be created and displayed on the calendar.
Always include INSERT statements for lookup/reference tables when running the schema.

### Spec extraction bug — Stage 2 times out with garbage spec

**Symptom:** Stage 1 compose runs fine (all steps complete), but the script reports:
```
Stage 1 done. Spec: /tmp/spec-XXXX-XXXXXXXXXX.md (8 lines)
```
Stage 2 then times out after 600s because `claude-code` receives a near-empty spec.

**Root cause:** Line 44 of `build-app.sh`:
```bash
cat "$SPEC_DIR"steps/*.md > "$SPEC_FILE" 2>/dev/null
```
The compose output directory's `steps/` glob doesn't always match or the files there
contain truncated "Got a bare dash" / "Hi! How can I help you?" garbage instead of
the actual design plan. The spec file ends up ~8 lines of useless text.

**Detection:** Before running Stage 2, check the spec file:
```bash
wc -l /tmp/spec-*.md
# If ≤ 10 lines → bug triggered. Abort the script, use manual recovery below.
```

**Recovery — manual Stage 2+3 (proven working, 2026-06-08):**

1. **Write the spec manually** from the compose output displayed in your terminal
   (you saw the full design plan from all the experts — Product Manager, UX Researcher,
   Database Architect, etc.). Write it to `/tmp/health-app-spec.md` (or similar).
   Include: product requirements, UX architecture, DB schema, design principles, tech stack.

2. **Run Stage 2 directly** (skip the script, run `ao` directly):
   ```bash
   cd ~/.hermes/workflows
   ao run finalize-app.yaml \
       --provider claude-code \
       --input description="<original user description>" \
       --input tg_user_id="<TG_USER_ID>" \
       --input spec=@"/tmp/health-app-spec.md" \
       --output ~/.hermes/ao-output/ \
       --quiet
   ```
   This takes ~3–5 minutes. Output should show "📡 已接收 9KB..." (db_architect)
   followed by "📡 已接收 38KB..." (frontend_coder). If exit code 0, Stage 2 succeeded.

3. **Extract the repo slug and run Stage 3:**
   ```bash
   FINAL_DIR=$(ls -dt ~/.hermes/ao-output/"App Builder — Finalize-"*/ | head -1)
   SLUG=$(grep -rhoE "REPO_SLUG:[[:space:]]*[a-z0-9-]+" "$FINAL_DIR/steps/1-db_architect.md" | head -1 | sed -E 's/REPO_SLUG:[[:space:]]*//')
   REPO_NAME="app-tg<TG_ID>-${SLUG}"
   python3 ~/.hermes/scripts/deploy-app.py \
       --mode create \
       --ao-output "$FINAL_DIR" \
       --repo-name "$REPO_NAME" \
       --tg-user-id "<TG_ID>"
   ```

4. **Get the live URL:**
   ```bash
   vercel list 2>/dev/null | grep "$SLUG" | head -1
   curl -s -o /dev/null -w "HTTP %{http_code}" "<URL>"
   # → HTTP 200
   ```

See `references/spec-extraction-bug.md` for the full reproduction transcript.

### Missing boilerplate files — deploy fails with "No Next.js version detected"

**Symptom:** Stage 3 succeeds (Neon + GitHub + Vercel created) but `vercel inspect` shows:
```
Error: No Next.js version detected. Make sure your package.json has "next"
```
The repo only has a `components/` directory — no `package.json`, `next.config.js`,
`app/`, `lib/`, or `middleware.js`.

**Root cause:** The `frontend_coder` step only generated app-specific component files
(e.g. `QuickLogModal.js`, `TrendsPanel.js`) but skipped ALL boilerplate files listed
in the workflow YAML. Claude Code sometimes treats the app-specific components as
"the output" and ignores the template requirements.

**Detection — after Stage 3, before reporting success:**
```bash
gh repo clone terenceng81/<REPO_NAME> /tmp/<REPO_NAME> -- --quiet
ls /tmp/<REPO_NAME>/package.json
# If missing → boilerplate bug triggered
```

**Recovery — generate all 15 missing files (proven working, 2026-06-08):**\n\nThe workflow's `finalize-app.yaml` lists these required files. Generate each one.\n\n**Quick start:** Copy the known-good templates from `templates/` — these cover the\n6 boilerplate files that NEVER change between apps (package.json, jsconfig.json,\nnext.config.js, middleware.js, lib/auth.js, lib/auth-client.js, lib/db.js).\nThen generate the app-specific files below.\n\n1. **Config files:** `package.json`, `jsconfig.json`, `next.config.js`, `middleware.js`
   - Use the exact templates from the workflow YAML (pinned versions, correct Next.js 14 API).
   - `next.config.js` MUST use `experimental.serverComponentsExternalPackages` (NOT `serverExternalPackages` — that's Next.js 15+).

2. **Auth layer:** `lib/auth.js`, `lib/auth-client.js`, `app/api/auth/[...all]/route.js`
   - Better Auth with Pool (not neon HTTP driver for auth — Pool is required).

3. **Database:** `lib/db.js` — neon HTTP client for server actions.

4. **App shell:** `app/layout.js`, `app/globals.css`
   - layout.js: Google Fonts (NOT Inter/Roboto), `suppressHydrationWarning`, inline theme script to prevent FOUC.
   - globals.css: Full design system — CSS variables for light/dark, all component classes, mobile responsive.

5. **Auth pages:** `app/page.js` (thin wrapper), `app/_client.js` (login/signup form)
   - `app/page.js`: `dynamic(() => import('./_client'), { ssr: false })` — REQUIRED for Better Auth React client.
   - `app/_client.js`: `'use client'`, `authClient.useSession()`, login/signup toggle.

6. **App dashboard shell:** `app/app/page.js` (thin wrapper), `app/app/_client.js` (main app UI)
   - Shell with bottom nav (mobile) + sidebar (desktop), theme toggle, sign out.
   - Renders the components generated by the frontend coder.

7. **Server actions:** `app/app/actions.js` — all mutations the components import.
   - Scan the generated component files to find all imports from `@/app/app/actions`.
   - Write a `requireUser()` helper and one `export async function` per imported action.
   - Match the DB schema that was deployed (check the `1-db_architect.md` step output).

**After generating all files:**
```bash
cd /tmp/<REPO_NAME>
git add -A && git commit -m "Fix: add all boilerplate files" && git push origin main
# Vercel auto-deploys on push. Wait ~60s then verify:
vercel inspect <URL> 2>&1 | grep status
# → status ● Ready
```

### Code block header with extra text — deploy regex misses files

**Symptom:** Stage 3 (deploy-app.py) reports `[ERROR] No code files found in ao output`
even though Stage 2 completed and `2-frontend_coder.md` has code blocks.

**Root cause:** The `parse_ao_output()` regex in `deploy-app.py` expects strict format:
```
**`filename.js`**
```js
...
`` `
```
But claude-code sometimes emits headers with trailing commentary:
```
**`app/app/_client.js`** *(continued — replace the incomplete file above with this full version)*
```
The regex `r'\*\*`([^`]+)`\*\*\s*\n` won't match when non-whitespace text follows `**`filename`**`.

**Detection — before running deploy-app.py:**
```bash
grep -c '\*\*`' <FINAL_DIR>/steps/2-frontend_coder.md
# If 0 or 1 → likely only one file emitted, or headers have extra text
# If the file is 25K+ but grep finds 0 files → regex is broken
```

**Recovery — extract code manually:**
```python
with open('<FINAL_DIR>/steps/2-frontend_coder.md') as f:
    lines = f.readlines()
in_block = False
code_lines = []
for line in lines:
    if line.strip() == '```js' and not in_block:
        in_block = True
        continue
    if line.strip() == '```' and in_block:
        break
    if in_block:
        code_lines.append(line)
with open('/tmp/<REPO>/app/app/_client.js', 'w') as out:
    out.writelines(code_lines)
```

After extracting the component code, follow the full manual boilerplate recovery
procedure in "Missing boilerplate files" above for everything else.

### Better Auth in Edge middleware — 500 error

**Symptom:** After deploying, the app returns HTTP 500. Vercel logs show:
```
[Error: The edge runtime does not support Node.js 'crypto' module.]
```
The error source is `edge-middleware`.

**Root cause:** Next.js 14 middleware runs in Edge runtime by default. Importing Better
Auth's `auth` object (which calls `auth.api.getSession()`) pulls in Node.js `crypto`
module, which Edge doesn't support. `export const runtime = 'nodejs'` is not supported
in Next.js 14 middleware — middleware MUST be Edge-compatible.

**Fix — cookie-only session check (no Better Auth import):**
```js
import { NextResponse } from 'next/server';

export default function middleware(request) {
  const { pathname } = request.nextUrl;
  if (pathname === '/' || pathname.startsWith('/api/auth') ||
      pathname.startsWith('/_next') || pathname.includes('.')) {
    return NextResponse.next();
  }
  // Better Auth uses __Secure- prefix in production (HTTPS), bare name in dev
  const sessionToken =
    request.cookies.get('__Secure-better-auth.session_token')?.value ||
    request.cookies.get('better-auth.session_token')?.value;
  if (!sessionToken) {
    return NextResponse.redirect(new URL('/', request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
```

**CRITICAL:** In production (HTTPS), Better Auth sets the session cookie as
`__Secure-better-auth.session_token`. The middleware MUST check both prefixed and
unprefixed cookie names. If only `better-auth.session_token` is checked, the middleware
always sees "no session" and redirects authenticated users back to `/`.

Server actions in `app/app/actions.js` still call `requireUser()` which does full
session validation server-side — the middleware is only a lightweight first-pass
redirect for unauthenticated users.

### Missing BETTER_AUTH_SECRET — all auth calls return 500

**Symptom:** After deploy, every auth endpoint (sign-up, sign-in, get-session) returns
HTTP 500 with empty body. Vercel logs show `⨯ [n [BetterAuthError…` truncated.

**Root cause:** Better Auth with `emailAndPassword` enabled requires
`BETTER_AUTH_SECRET` for token signing/encryption. The deploy script sets
`DATABASE_URL` but NOT `BETTER_AUTH_SECRET`. Without it, Better Auth throws on every
request because it can't sign session tokens.

**Detection:**
```bash
cd /tmp/<REPO_NAME> && vercel env ls 2>&1 | grep BETTER_AUTH_SECRET
# If no output → missing!
```

**Fix:**
```bash
# Generate a random secret and add it to Vercel
BETTER_AUTH_SECRET=$(openssl rand -base64 32)
echo "$BETTER_AUTH_SECRET" | vercel env add BETTER_AUTH_SECRET production
# Then redeploy
vercel --prod --yes
```

**Prevention:** After every `build-app.sh create`, immediately add this env var
before the user tries to sign up. This is ALWAYS needed for email/password auth.

### Missing baseURL / BETTER_AUTH_URL — build warnings, redirect issues

**Symptom:** Vercel build logs show:
```
WARN [Better Auth]: Base URL could not be determined. Please set a valid base URL
using the baseURL config option or the BETTER_AUTH_URL environment variable.
```
This can cause broken redirects and callback URL mismatches in production.

**Fix — two-part:**

1. Add the Vercel env var:
   ```bash
   echo "https://<app-name>.vercel.app" | vercel env add BETTER_AUTH_URL production
   ```

2. Update `lib/auth.js` to use it:
   ```js
   export const auth = betterAuth({
     database: new Pool({ connectionString: process.env.DATABASE_URL }),
     baseURL: process.env.BETTER_AUTH_URL || process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000',
     // ... rest of config
   });
   ```

### Example SQL queries with `$1` placeholders — harmless psql errors

**Symptom:** When applying the schema via `psql -f`, you see errors like:
```
ERROR: there is no parameter $1
```
But the CREATE TABLE statements succeeded and all tables exist.

**Root cause:** The `1-db_architect.md` output includes example queries (for documentation)
that use PostgreSQL parameter placeholders (`$1`, `$2`). These are not schema DDL — they're
usage examples that get included when extracting all ```` ```sql ```` blocks.

**Ignore these errors.** Verify tables exist after schema apply:
```bash
psql -c "\dt"
```
If all expected tables are listed, the schema applied correctly despite the param errors.

### `build-app.sh delete` mode silently drops the repo name

**Symptom:** Running `bash build-app.sh delete "app-tg8724348754-my-app"` prints usage
and exits 1 without deleting.

**Root cause:** Line 9 of `build-app.sh` does `shift 2` unconditionally. Create and update
modes have 3+ args, so after shift the remaining args are correct. But delete mode only
has 2 args total (mode + repo_name), so after `shift 2` nothing remains and `$1` is empty.

**Workaround:** Pass a dummy second argument before the repo name:
```bash
bash ~/.hermes/scripts/build-app.sh delete "dummy" "app-tg8724348754-my-app"
```

**Permanent fix (not yet applied to the script):**
Move `shift 2` inside the `create`/`update` branches so it doesn't run for `delete`.

### `;` inside SQL inline comments breaks Neon schema parsing

**Symptom:** Deploy fails at Stage 3 with:
```
[Neon] SQL error: {'S': 'ERROR', ... 'M': 'syntax error at end of input'}
```

**Root cause:** The `neon_run_sql` function in `deploy-app.py` strips lines starting with
`--` but not inline `--` comments. Then it splits on `;` — if an inline comment contains
a semicolon (e.g. `-- NULL while in progress; set on stop/complete`), the split produces
a garbage SQL fragment that fails PostgreSQL parsing.

**Fix (applied 2026-06-08):** `deploy-app.py` now strips ALL `--` comments before splitting:
```python
no_comments = re.sub(r'--[^\n]*', '', sql)
```

**Prevention for new schemas:** Avoid semicolons in SQL inline comments. Write:
```sql
ended_at TIMESTAMPTZ,  -- NULL while in progress, set on stop/complete
```
not:
```sql
ended_at TIMESTAMPTZ,  -- NULL while in progress; set on stop/complete
```

### `sql.unsafe() is not a function — @neondatabase/serverless API mismatch

**Symptom:** API routes return `{ "error": "o.i.unsafe is not a function" }` (500).

**Root cause:** `@neondatabase/serverless` exports `neon()` which returns a tagged template
function, not an object with `.unsafe()`. Code like `sql.unsafe(queryStr, params)` will fail.

**Correct pattern — use tagged template literals directly:**
```js
// ❌ WRONG
const classes = await sql.unsafe(query, params)

// ✅ RIGHT — embed values directly in template
const classes = await sql`SELECT * FROM table WHERE id = ${id} AND name = ${name}`
```

For dynamic queries, pre-build the query by embedding values into the template string.
The neon function handles parameter binding automatically.

**Detection:** If you see `sql.unsafe` in any route file, replace it immediately.

### Line number corruption — NEVER pass read_file output to write_file

**Symptom:** Files on disk have `1|`, `2|` line number prefixes after using `read_file` +
`write_file` in execute_code, causing JS syntax errors on Vercel build:
```
x Unexpected token `{`. Expected `.` or `(`
```

**Root cause:** `read_file` returns content WITH line number prefixes (`1|'use client'`).
Passing that output to `write_file` writes the numbers into the actual file.

**Recovery:** Revert with `git checkout <commit> -- <files>`, then use `sed` or `patch`:
```bash
# ✅ Correct — safe in-place replacement
sed -i '' 's/start_time/starts_at/g' app/schedule/_client.js

# ❌ Wrong — poisons the file
content = read_file("file.js")
content = content.replace("start_time", "starts_at")
write_file("file.js", content)
```

### Missing dependencies — build fails with module not found

**Symptom:** Vercel build fails because components import libraries not listed
in the workflow's `package.json` template (e.g. `recharts`, `next-themes`).

**Root cause:** The frontend coder generates components that use charting libraries
or theme providers, but the workflow's `package.json` template only includes
`next`, `react`, `react-dom`, `better-auth`, `@neondatabase/serverless`, and `pg`.

**Detection:** After Stage 2 completes, scan component imports for external deps:
```bash
python3 -c "
import re
with open('<FINAL_DIR>/steps/2-frontend_coder.md') as f:
    content = f.read()
known = {'react','next','better-auth','recharts','@neondatabase'}
for m in re.finditer(r\"from ['\\\"]([^'\\\"@.][^'\\\"]+)['\\\"]\", content):
    if m.group(1) not in known:
        print(f'MISSING: {m.group(1)}')
"
```

**Recovery:** Add the missing libraries to `package.json` before pushing:
```json
"recharts": "^2.12.7",
"next-themes": "^0.3.0"
```

### Neon database name mismatch — schema goes to wrong database

**Symptom:** Schema applied successfully (psql reports OK), but API returns empty arrays
or connection errors. The Neon project has multiple databases (`neondb` is the default;
app tables are in a separate one like `yoga`).

**Root cause:** The Vercel `DATABASE_URL` env var gets set to the project's default pooled
connection, which points to `neondb` not the app's database. All API queries run against
an empty database.

**Detection:**
```bash
# Check what DB the URI actually points to
echo $VERCEL_DATABASE_URL | grep -o '/[^/?]*?' | head -1
# If it says '/neondb' instead of '/yoga' or your app DB → mismatch
```

**Recovery:** Update the Vercel env var to the correct pooled URI:
```python
# Get correct pooled URI from Neon API
GET /projects/{pid}/connection_uri?database_name=yoga&role_name=neondb_owner&pooled=true
# Patch the Vercel env var via API
PATCH /v9/projects/{repo}/env/{env_id}
Body: {"value": "<correct_uri>", "target": ["production", "preview", "development"], "type": "encrypted"}
```
Then redeploy: `vercel --prod --yes`

### React hooks in nested components — crashes with error #311

**Symptom:** App loads then shows "Application error: a client-side exception has occurred."
Console shows React error #311: "Rendered more hooks than during the previous render."

**Root cause:** A component that uses hooks (e.g. `AppShell` with `useState`, `useEffect`)
is defined INSIDE another component's render body. React sees a new function identity each
render, breaking the Rules of Hooks.

```jsx
// ❌ WRONG — Shell uses hooks inside Component's body
function Component() {
  function Shell({ children }) {  // recreated every render!
    const [pathname, setPathname] = useState('')  // hooks violation
    return <nav>...</nav>
  }
  return <Shell>...</Shell>
}

// ✅ RIGHT — standalone function outside any component
function TopNav({ session }) {
  const [pathname, setPathname] = useState('')
  return <nav>...</nav>
}
function Component() {
  return <div><TopNav session={session} />...</div>
}
```

**Fix:** Extract ALL hook-using sub-components (`Shell`, `AppShell`, `TopNav`) to top-level
module-scope functions. Never define a hook-using component inside another component's body.

See `references/boilerplate-recovery.md` for the complete file-generation reference.
