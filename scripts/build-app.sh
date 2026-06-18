#!/bin/bash
# build-app.sh — one-shot app builder
# Usage: bash build-app.sh create <tg_user_id> <tg_username> <description>
#        bash build-app.sh update <tg_user_id> <repo_name> <update_request>
set -e

MODE=$1
TG_USER_ID=$2
shift 2

HERMES_DIR="$HOME/.hermes"
WORKFLOWS_DIR="$HOME/.hermes/workflows"
AO_OUTPUT_DIR="$HOME/.hermes/ao-output"
SCRIPTS_DIR="$HERMES_DIR/scripts"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ── CREATE ────────────────────────────────────────────────────────────────────
if [ "$MODE" = "create" ]; then
    TG_USERNAME=$1
    DESCRIPTION=$2
    # 4th arg = provider for THIS build. Default claude-code (the setup that first built apps, via claude CLI oauth).
    #   claude-code → calls the claude CLI (oauth), runs dynamic compose team + finalize, best quality (recommended)
    #   hermes-cli  → Hermes's currently configured gateway model (whatever config.yaml says), skips compose, fixed finalize only
    PROVIDER=${3:-claude-code}
    case "$PROVIDER" in claude-code|hermes-cli) ;; *) PROVIDER=hermes-cli ;; esac

    log "Starting app creation for user $TG_USER_ID (provider: $PROVIDER)"
    log "Description: $DESCRIPTION"

    cd "$WORKFLOWS_DIR"
    SPEC_FILE="/tmp/spec-$$-$(date +%s).md"

    if [ "$PROVIDER" = "claude-code" ]; then
        # ── Stage 1: DYNAMIC — ao compose convenes experts (needs strong model)
        log "Stage 1: ao compose — dynamically convening expert team (claude-code)..."
        COMPOSE_DESC="Design and plan a full-stack Next.js 14 web application (App Router, deployed to Vercel).\
User requirement: ${DESCRIPTION}.\
CONSTRAINTS: (1) Mobile-first — all layouts must work at 375px first, then scale up. (2) Pick one deliberate aesthetic direction (minimalist / retro-futuristic / organic-natural / luxe-refined / playful-toy / editorial-magazine / brutalist / geometric-art-deco / soft-macaron / industrial-utilitarian) and name it explicitly in the spec so the coder carries it through. (3) Auth and database are conditional — only include if the app truly needs multi-user data or cross-device sync.\
Convene the right experts: requirements analysis, UX flows, UI design direction (with explicit aesthetic choice), data model, and feature list.\
Produce the design plan only — do not write the final code."
        ao compose "$COMPOSE_DESC" --run --provider claude-code --lang en \
            --output "$AO_OUTPUT_DIR/" --quiet
        SPEC_DIR=$(ls -dt "$AO_OUTPUT_DIR"/*/ 2>/dev/null | head -1)
        cat "$SPEC_DIR"steps/*.md > "$SPEC_FILE" 2>/dev/null || cat "$SPEC_DIR"*.md > "$SPEC_FILE" 2>/dev/null
        log "Stage 1 done. Spec: $SPEC_FILE ($(wc -l < "$SPEC_FILE") lines)"
    else
        # Local model uses the fixed flow (skips compose's dynamic role selection) — use the request itself as the spec
        log "Stage 1: skipped (provider=$PROVIDER → fixed flow, no dynamic compose). Using description as spec."
        printf 'User requirement: %s\n' "$DESCRIPTION" > "$SPEC_FILE"
    fi

    # ── Stage 2: FIXED quality gate — design + karpathy + Neon + format ─────
    # Same provider drives the actual codegen. --provider overrides the YAML.
    log "Stage 2: finalize — frontend-design + karpathy + Neon templates (provider: $PROVIDER)..."
    ao run finalize-app.yaml \
        --provider "$PROVIDER" \
        --input description="$DESCRIPTION" \
        --input tg_user_id="$TG_USER_ID" \
        --input spec=@"$SPEC_FILE" \
        --output "$AO_OUTPUT_DIR/" \
        --quiet

    FINAL_DIR=$(ls -dt "$AO_OUTPUT_DIR"/*/ 2>/dev/null | head -1)

    # Derive repo name from the REPO_SLUG the finalize step emitted
    # Only scan the db_architect step output — the metadata.json may contain old
    # compose specs with stale slugs, and our template example text also mentions one.
    SLUG=$(grep -rhoE "REPO_SLUG:[[:space:]]*[a-z0-9-]+" "$FINAL_DIR/steps/1-db_architect.md" 2>/dev/null | head -1 | sed -E 's/REPO_SLUG:[[:space:]]*//')
    if [ -z "$SLUG" ]; then SLUG="app"; fi
    REPO_NAME="app-tg${TG_USER_ID}-${SLUG}"
    log "Stage 2 done. Repo: $REPO_NAME"

    # ── Stage 3: deploy — Neon + GitHub + Vercel ────────────────────────────
    log "Stage 3: deploying (Neon + GitHub + Vercel)..."
    python3 "$SCRIPTS_DIR/deploy-app.py" \
        --mode create \
        --ao-output "$FINAL_DIR" \
        --repo-name "$REPO_NAME" \
        --tg-user-id "$TG_USER_ID" \
        --description "$DESCRIPTION"

    rm -f "$SPEC_FILE"

# ── UPDATE ────────────────────────────────────────────────────────────────────
elif [ "$MODE" = "update" ]; then
    REPO_NAME=$1
    UPDATE_REQUEST=$2
    PROVIDER=${3:-claude-code}
    case "$PROVIDER" in claude-code|hermes-cli) ;; *) PROVIDER=hermes-cli ;; esac

    log "Starting app update for repo $REPO_NAME (provider: $PROVIDER)"

    # Clone existing repo
    TMPDIR="/tmp/update-$(date +%s)"
    log "Cloning $REPO_NAME..."
    gh repo clone "terenceng81/$REPO_NAME" "$TMPDIR" -- --quiet

    # Build file list and read key files (Next.js App Router structure)
    FILE_LIST=$(find "$TMPDIR/app" "$TMPDIR/lib" -name "*.js" -o -name "*.css" 2>/dev/null | sed "s|$TMPDIR/||" | tr '\n' ' ')
    EXISTING_CODE=$(cat "$TMPDIR/app/app/page.js" "$TMPDIR/app/page.js" "$TMPDIR/app/globals.css" 2>/dev/null | head -500)

    log "Running ao update pipeline..."
    cd "$WORKFLOWS_DIR"
    ao run update-app.yaml \
        --provider "$PROVIDER" \
        --input tg_user_id="$TG_USER_ID" \
        --input repo_name="$REPO_NAME" \
        --input update_request="$UPDATE_REQUEST" \
        --input existing_file_list="$FILE_LIST" \
        --input existing_code="$EXISTING_CODE" \
        --output "$AO_OUTPUT_DIR/" \
        --quiet

    log "ao pipeline complete. Running deploy script..."

    python3 "$SCRIPTS_DIR/deploy-app.py" \
        --mode update \
        --tg-user-id "$TG_USER_ID" \
        --repo-dir "$TMPDIR"

    # Cleanup
    rm -rf "$TMPDIR"

# ── DELETE ───────────────────────────────────────────────────────────────────
elif [ "$MODE" = "delete" ]; then
    REPO_NAME=$1
    if [ -z "$REPO_NAME" ]; then
        echo "Usage: $0 delete <repo_name>"
        echo "  e.g. $0 delete app-tg8724348754-expense-tracker"
        exit 1
    fi

    APPS_JSON="$HERMES_DIR/app-builder/apps.json"
    GITHUB_OWNER="${GITHUB_OWNER:-terenceng81}"

    # Source .env for API keys
    # shellcheck disable=SC1090
    [ -f "$HERMES_DIR/.env" ] && source "$HERMES_DIR/.env"

    log "Deleting app: $REPO_NAME"

    # 1. Neon — delete project
    NEON_PROJECT_ID=$(python3 -c "import json,sys; d=json.load(open('$APPS_JSON')); print(d.get('$REPO_NAME',{}).get('project_id',''))" 2>/dev/null)
    if [ -n "$NEON_PROJECT_ID" ] && [ -n "$NEON_API_KEY" ]; then
        log "Deleting Neon project $NEON_PROJECT_ID..."
        HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
            "https://console.neon.tech/api/v2/projects/$NEON_PROJECT_ID" \
            -H "Authorization: Bearer $NEON_API_KEY")
        if [ "$HTTP" = "200" ] || [ "$HTTP" = "204" ]; then
            log "Neon project deleted."
        else
            log "WARNING: Neon delete returned HTTP $HTTP (may already be deleted)."
        fi
    else
        log "No Neon project found in registry (skipping)."
    fi

    # 2. Vercel — delete project by name
    if [ -n "$VERCEL_TOKEN" ]; then
        log "Deleting Vercel project $REPO_NAME..."
        VERCEL_URL="https://api.vercel.com/v9/projects/$REPO_NAME"
        [ -n "$VERCEL_TEAM_ID" ] && VERCEL_URL="$VERCEL_URL?teamId=$VERCEL_TEAM_ID"
        HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$VERCEL_URL" \
            -H "Authorization: Bearer $VERCEL_TOKEN")
        if [ "$HTTP" = "200" ] || [ "$HTTP" = "204" ]; then
            log "Vercel project deleted."
        else
            log "WARNING: Vercel delete returned HTTP $HTTP (may already be deleted)."
        fi
    else
        log "No VERCEL_TOKEN found (skipping Vercel delete)."
    fi

    # 3. Cloudflare — delete CNAME record for custom domain
    SLUG=$(echo "$REPO_NAME" | sed "s/app-tg[0-9]*-//")
    CF_TOKEN=$(python3 -c "import os,re; lines=open(os.path.expanduser('~/.hermes/.env')).readlines(); t=[l.split('=',1)[1].strip().strip('\"\'') for l in lines if l.startswith('CLOUDFLARE_API_TOKEN')]; print(t[0] if t else '')" 2>/dev/null)
    CF_ZONE=$(python3 -c "import os,re; lines=open(os.path.expanduser('~/.hermes/.env')).readlines(); t=[l.split('=',1)[1].strip().strip('\"\'') for l in lines if l.startswith('CLOUDFLARE_ZONE_ID')]; print(t[0] if t else '')" 2>/dev/null)
    CF_BASE=$(python3 -c "import os,re; lines=open(os.path.expanduser('~/.hermes/.env')).readlines(); t=[l.split('=',1)[1].strip().strip('\"\'') for l in lines if l.startswith('CUSTOM_DOMAIN_BASE')]; print(t[0] if t else 'nhkclouds.com')" 2>/dev/null)
    if [ -n "$CF_TOKEN" ] && [ -n "$CF_ZONE" ]; then
        RECORD_ID=$(curl -s "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records?type=CNAME&name=$SLUG.$CF_BASE" \
            -H "Authorization: Bearer $CF_TOKEN" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result'][0]['id'] if d.get('result') else '')" 2>/dev/null)
        if [ -n "$RECORD_ID" ]; then
            HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
                "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records/$RECORD_ID" \
                -H "Authorization: Bearer $CF_TOKEN")
            [ "$HTTP" = "200" ] && log "Cloudflare CNAME $SLUG.$CF_BASE deleted." || log "WARNING: Cloudflare CNAME delete returned HTTP $HTTP."
        else
            log "No Cloudflare CNAME found for $SLUG.$CF_BASE (skipping)."
        fi
    else
        log "No Cloudflare credentials (skipping CNAME delete)."
    fi

    # 4. GitHub — delete repo
    log "Deleting GitHub repo $GITHUB_OWNER/$REPO_NAME..."
    if gh repo delete "$GITHUB_OWNER/$REPO_NAME" --yes 2>/dev/null; then
        log "GitHub repo deleted."
    else
        log "WARNING: GitHub repo delete failed (may already be deleted)."
    fi

    # 5. Remove from registry
    if python3 - <<PYEOF
import json, sys
try:
    with open('$APPS_JSON') as f:
        data = json.load(f)
    if '$REPO_NAME' in data:
        del data['$REPO_NAME']
        with open('$APPS_JSON', 'w') as f:
            json.dump(data, f, indent=2)
        print("Registry entry removed.")
    else:
        print("Not in registry (already clean).")
except Exception as e:
    print(f"Registry update skipped: {e}", file=sys.stderr)
PYEOF
    then
        log "Registry updated."
    fi

    log "Done. $REPO_NAME has been fully deleted."

else
    echo "Usage: $0 create <tg_user_id> <tg_username> <description> [provider]"
    echo "       $0 update <tg_user_id> <repo_name> <update_request> [provider]"
    echo "       $0 delete <repo_name>"
    echo "       provider = claude-code | hermes-cli  (default: claude-code)"
    exit 1
fi
