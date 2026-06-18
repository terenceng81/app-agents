# Spec Extraction Bug — Reproduction (2026-06-08)

## The Bug

`build-app.sh` line 44:
```bash
cat "$SPEC_DIR"steps/*.md > "$SPEC_FILE" 2>/dev/null || cat "$SPEC_DIR"*.md > "$SPEC_FILE" 2>/dev/null
```

The compose output directory's `steps/*.md` files either don't exist (empty glob) or
contain truncated garbage. The fallback `cat "$SPEC_DIR"*.md` grabs the root `summary.md`
which is a ~465-byte workflow summary, not the design plan.

Result: spec file is 8 lines:
```
> 🗄️ **Database Architect** | 步骤 1/2 | 6.6s
---
Got a bare dash — looks like maybe the message got cut off? What can I help with?
> ⚛️ **Full-Stack Developer** | 步骤 2/2 | 4.1s
---
Hi Terence! How can I help you today?
```

Stage 2 finalize (line 55-61) feeds this garbage as `{{spec}}` to `claude-code`, which
has nothing to work from and times out after 600s.

## Full Reproduction

### Attempt 1 — build script, 600s timeout
```
bash ~/.hermes/scripts/build-app.sh create "8724348754" "NHKClouds" "Build a health tracking app..."
```
- Stage 1 (compose): ✅ 6/6 experts, 214.8s — great design plan produced
- Stage 1 spec: `/tmp/spec-9686-1780879544.md (8 lines)` ← BUG
- Stage 2 (finalize): ❌ timed out after 600s, no Finalize dir created

### Attempt 2 — build script, 600s timeout (same bug)
```
bash ~/.hermes/scripts/build-app.sh create "8724348754" "NHKClouds" "Build a health tracking app..."
```
- Stage 1 (compose): ✅ 7/7 experts, 271.8s — another great design plan
- Stage 1 spec: `/tmp/spec-10804-1780880166.md (8 lines)` ← BUG
- Stage 2 (finalize): ❌ timed out after 600s

### Attempt 3 — manual compose, 300s timeout
```
ao compose "..." --run --provider claude-code
```
- 4/8 steps completed (Product Manager, UX Researcher, Database Architect, Software Architect)
- Timed out during UX Architect step

### Attempt 4 — manual Stage 2+3 (FIX, SUCCESS)
1. Wrote comprehensive spec to `/tmp/health-app-spec.md` (7KB, from compose output)
2. `ao run finalize-app.yaml --provider claude-code --input spec=@"/tmp/health-app-spec.md"` → ✅
   - db_architect: 8,407 bytes
   - frontend_coder: 38,201 bytes
3. `python3 deploy-app.py --mode create ...` → ✅
   - Neon: red-rice-10704164, 18 SQL statements
   - GitHub: terenceng81/app-tg8724348754-health-pulse
   - Vercel: deployed, HTTP 200

## Key Insight

When the build script reports `Spec: ... (8 lines)`, **abort immediately**. Running
Stage 2 with a garbage spec always times out. The manual recovery path (write spec
from compose output → `ao run finalize-app.yaml` → `deploy-app.py`) bypasses the
broken spec extraction and works reliably.
