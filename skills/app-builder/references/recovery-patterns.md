# Recovery Patterns — App Builder

## Pattern 1: Stage 3 timeout → manual deploy (EXPENSE TRACKER, 2026-06-07)

**Symptom:** Script output ends with:
```
Stage 2 done. Repo: app-tg8724348754-expense-tracker
Stage 3: deploying (Neon + GitHub + Vercel)...
[Command timed out after 600s]
```

**Root cause:** Vercel deployment is slow; the script's 600s timeout is hit.

**Recovery steps (verified working):**
```bash
# 1. Confirm repo exists
gh repo view terenceng81/app-tg8724348754-expense-tracker --json name,url
# → {"name":"app-tg8724348754-expense-tracker","pushedAt":"..."}

# 2. Find the FINAL_DIR
FINAL_DIR=$(ls -dt ~/.hermes/ao-output/"App Builder — Finalize-"/ | head -1)
# → .../App Builder — Finalize-2026-06-07T19-59-48/

# 3. Run deploy manually
python3 ~/.hermes/scripts/deploy-app.py \
    --mode create \
    --ao-output "$FINAL_DIR" \
    --repo-name "app-tg8724348754-expense-tracker" \
    --tg-user-id "8724348754"

# Output:
# [Neon] Project: gentle-grass-22988347
# [Neon] Ran 9 SQL statements OK
# [Vercel] Timeout waiting for deployment (but deployment continues)

# 4. Get the live URL (deployment finishes moments later)
vercel list 2>/dev/null | grep "expense" | head -1
# → https://app-tg8724348754-expense-tracker-ow13btpcg-nhkclouds.vercel.app

# 5. Verify with curl
curl -s -o /dev/null -w "%{http_code}" "<URL>"
# → 200
```

## Pattern 2: Stage 2 timeout → claude-code still running

**Symptom:** Script output ends with:
```
Stage 2: finalize — frontend-design + karpathy + Neon templates (provider: claude-code)...
  📡 已接收 9.7KB...
[Command timed out after 600s]
```

**Root cause:** The claude-code finalize step is generating the full Next.js codebase and takes >600s.

**Recovery:** Check if the child process is still alive:
```bash
ps aux | grep "resume 763d480b" | grep -v grep
# PID 53294 ... cputime 3:39.91 ... (still progressing)
```

If CPU time is incrementing: WAIT. Poll every 60s until a new Finalize dir appears.
If CPU time is frozen: kill it and restart (max 2 restarts due to session limits).

## Pattern 3: Claude Code session limit

**Symptom:**
```
失败: Claude Code CLI 错误: You've hit your session limit · resets 8:10am (Asia/Singapore)
```

**Action:** Stop all retries immediately. Tell user the reset time. Offer to schedule retry.
Session limits are hourly — retrying wastes tokens without making progress.

## Pattern 4: hermes-cli produces empty output

**Symptom:**
```
[05:17:35] Stage 2 done. Repo: app-tg8724348754-app
[ERROR] No code files found in ao output. Check the ao run completed successfully.
```

**Root cause:** hermes-cli completes the finalize step in 11 seconds but generates no code.
metadata.json is ~1KB vs ~36KB for claude-code. Do not use hermes-cli.

## Pattern 5: Spec extraction bug → Stage 2 times out (HEALTH PULSE, 2026-06-08)

**Symptom:** Stage 1 compose completes successfully (all expert steps visible in output),
but the script reports `Spec: /tmp/spec-XXXX.md (8 lines)`. Stage 2 then times out after
600s because claude-code gets a near-empty spec with "Got a bare dash" garbage.

**Root cause:** `build-app.sh` line 44's `cat "$SPEC_DIR"steps/*.md` glob doesn't match or
picks up truncated files. The compose output is visible in terminal but never lands in the spec.

**Recovery:** See `references/spec-extraction-bug.md` for the full transcript, or the
"Spec extraction bug" section in SKILL.md for the step-by-step manual Stage 2+3 procedure.

## Pattern 6: Missing boilerplate — deploy succeeds but build fails (HEALTH PULSE, 2026-06-08)

**Symptom:** Deploy script reports success (Neon + GitHub + Vercel created), but
`vercel inspect` shows `Error: No Next.js version detected`. The repo only has
a `components/` directory — no `package.json`, `next.config.js`, `app/`, `lib/`,
or `middleware.js`.

**Root cause:** The frontend_coder step (claude-code) only generated app-specific
component files (QuickLogModal.js, TrendsPanel.js, etc.) but skipped all 15 required
boilerplate files listed in `finalize-app.yaml`.

**Recovery:** See `references/boilerplate-recovery.md` for the complete 8-step
file-generation procedure with exact templates for every required file.

## Pattern 7: Missing dependencies — build fails with module not found (HEALTH PULSE, 2026-06-08)

**Symptom:** After fixing boilerplate, Vercel build fails because components import
libraries not in `package.json` (e.g. `recharts`, `next-themes`).

**Root cause:** The frontend coder generates components using charting/theming libraries,
but the workflow's `package.json` template only includes core deps (next, react, better-auth,
neon, pg).

**Recovery:** Scan component imports for external libs and add to `package.json`:
```bash
python3 -c "
import re
with open('<FINAL_DIR>/steps/2-frontend_coder.md') as f:
    content = f.read()
known = {'react','next','better-auth','recharts','@neondatabase','next-themes'}
for m in re.finditer(r\"from ['\\\"]([^'\\\"@.][^'\\\"]+)['\\\"]\", content):
    if m.group(1) not in known:
        print(f'ADD: {m.group(1)}')
"
```
Add the discovered deps to `package.json`, commit, and push.

## Key Files Reference

- Build script: `~/.hermes/scripts/build-app.sh` (3-stage pipeline)
- Deploy script: `~/.hermes/scripts/deploy-app.py` (Neon + GitHub + Vercel)
- Finalize workflow: `~/.hermes/workflows/finalize-app.yaml` (2-step: db_architect → frontend_coder)
- AO output: `~/.hermes/ao-output/App Builder — Finalize-<timestamp>/`
- Spec files: `/tmp/spec-<id>-<timestamp>.md` (compose output, check with `wc -l` — ≤10 lines = broken)
- Boilerplate templates: `references/boilerplate-recovery.md` (all 15 files with exact code)
- Spec extraction recovery: `references/spec-extraction-bug.md`
