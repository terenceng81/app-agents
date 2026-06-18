#!/usr/bin/env python3
"""
deploy-app.py — App Builder deployment script
Parses ao markdown output → provisions a database (Neon or Supabase) →
creates GitHub repo + pushes code → deploys to Vercel → returns live URL.

Database layer is pluggable via DB_PROVIDER (neon | supabase).
- neon:     one isolated Postgres project per app (Better Auth + @neondatabase/serverless)
- supabase: one shared project, table-per-app with RLS
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.error


# ── Env ──────────────────────────────────────────────────────────────────────

def load_env():
    env_path = Path.home() / ".hermes" / ".env"
    env = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV = load_env()

GITHUB_TOKEN      = ENV.get("GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
VERCEL_TOKEN      = ENV.get("VERCEL_TOKEN") or os.environ.get("VERCEL_TOKEN")
VERCEL_TEAM_ID    = ENV.get("VERCEL_TEAM_ID") or os.environ.get("VERCEL_TEAM_ID", "")
GITHUB_OWNER      = ENV.get("GITHUB_OWNER") or os.environ.get("GITHUB_OWNER", "terenceng81")

DB_PROVIDER       = (ENV.get("DB_PROVIDER") or os.environ.get("DB_PROVIDER", "neon")).lower()

# Cloudflare + custom domain
CLOUDFLARE_API_TOKEN = ENV.get("CLOUDFLARE_API_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ZONE_ID   = ENV.get("CLOUDFLARE_ZONE_ID") or os.environ.get("CLOUDFLARE_ZONE_ID", "")
CUSTOM_DOMAIN_BASE   = ENV.get("CUSTOM_DOMAIN_BASE") or os.environ.get("CUSTOM_DOMAIN_BASE", "nhkclouds.com")

# Neon
NEON_API_KEY      = ENV.get("NEON_API_KEY") or os.environ.get("NEON_API_KEY")
NEON_REGION       = ENV.get("NEON_REGION") or os.environ.get("NEON_REGION", "aws-ap-southeast-1")

# Supabase (legacy / shared-project mode)
SUPABASE_URL      = ENV.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
SUPABASE_SVC_KEY  = ENV.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
SUPABASE_ANON_KEY = ENV.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_ANON_KEY")

# Per-app registry — remembers which Neon project belongs to which repo (for updates)
REGISTRY_PATH = Path.home() / ".hermes" / "app-builder" / "apps.json"


def check_env(mode):
    required = {"GITHUB_TOKEN": GITHUB_TOKEN, "VERCEL_TOKEN": VERCEL_TOKEN}
    if mode == "create":
        if DB_PROVIDER == "neon":
            required["NEON_API_KEY"] = NEON_API_KEY
        elif DB_PROVIDER == "supabase":
            required.update({
                "SUPABASE_URL": SUPABASE_URL,
                "SUPABASE_SERVICE_KEY": SUPABASE_SVC_KEY,
                "SUPABASE_ANON_KEY": SUPABASE_ANON_KEY,
            })
        else:
            print(f"[ERROR] Unknown DB_PROVIDER: {DB_PROVIDER} (expected neon or supabase)")
            sys.exit(1)
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[ERROR] Missing env vars in ~/.hermes/.env: {', '.join(missing)}")
        sys.exit(1)


# ── App registry (per-app DB credentials, for the update flow) ────────────────

def registry_load() -> dict:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text())
        except Exception:
            return {}
    return {}


def registry_save(repo_name: str, info: dict):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = registry_load()
    data[repo_name] = info
    REGISTRY_PATH.write_text(json.dumps(data, indent=2))


def registry_get(repo_name: str) -> dict:
    return registry_load().get(repo_name, {})


# ── Markdown parser ───────────────────────────────────────────────────────────

def parse_ao_output(ao_dir: Path) -> dict[str, str]:
    """
    Scans all .md files in the ao output dir.
    Extracts code blocks preceded by a **`filename`** header.
    Returns {filepath: content}.
    """
    files = {}
    pattern = re.compile(
        r'\*\*`([^`]+)`\*\*\s*\n```[^\n]*\n(.*?)```',
        re.DOTALL
    )

    for md_file in sorted(ao_dir.glob("**/*.md")):
        text = md_file.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            filepath = match.group(1).strip()
            content  = match.group(2)
            files[filepath] = content

    return files


def extract_schema_sql(ao_dir: Path) -> Optional[str]:
    """Finds schema.sql content in ao output. Returns None if no DB is needed
    (NO_DATABASE_NEEDED marker) or if no schema block is present."""
    no_db = re.compile(r'NO_DATABASE_NEEDED', re.IGNORECASE)
    pattern = re.compile(r'```sql\s*\n(-- schema\.sql.*?)```', re.DOTALL | re.IGNORECASE)
    for md_file in sorted(ao_dir.glob("**/*.md")):
        text = md_file.read_text(encoding="utf-8", errors="replace")
        if no_db.search(text):
            return None
        m = pattern.search(text)
        if m:
            return m.group(1).strip()
    return None


def extract_migration_sql(ao_dir: Path) -> str | None:
    """Finds migration.sql content. Returns None if NO_MIGRATION_NEEDED."""
    pattern = re.compile(r'```sql\s*\n(-- migration\.sql.*?)```', re.DOTALL | re.IGNORECASE)
    no_migration = re.compile(r'NO_MIGRATION_NEEDED', re.IGNORECASE)
    for md_file in sorted(ao_dir.glob("**/*.md")):
        text = md_file.read_text(encoding="utf-8", errors="replace")
        if no_migration.search(text):
            return None
        m = pattern.search(text)
        if m:
            return m.group(1).strip()
    return None


# ── Neon ──────────────────────────────────────────────────────────────────────

def neon_request(method: str, path: str, payload: Optional[dict] = None) -> Optional[dict]:
    url = f"https://console.neon.tech/api/v2{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {NEON_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        print(f"  [Neon] {method} {path} → {e.code}: {e.read().decode(errors='replace')}")
        return None


def neon_create_project(repo_name: str) -> Optional[dict]:
    """Creates an isolated Neon project. Returns dict with project_id, branch_id,
    db_name, connection_uri."""
    resp = neon_request("POST", "/projects", {
        "project": {
            "name": repo_name,
            "region_id": NEON_REGION,
            "pg_version": 17,
        }
    })
    if not resp:
        return None
    project = resp["project"]
    conn = resp["connection_uris"][0]
    branch_id = resp["roles"][0]["branch_id"]
    db_name = resp["databases"][0]["name"]
    return {
        "project_id": project["id"],
        "branch_id": branch_id,
        "db_name": db_name,
        "connection_uri": conn["connection_uri"],
    }


def neon_run_sql(connection_uri: str, sql: str) -> bool:
    """Runs DDL/SQL against a Neon Postgres branch using pg8000 (pure Python)."""
    try:
        import pg8000.native
    except ImportError:
        print("  [Neon] pg8000 not installed. Run: pip install pg8000")
        return False

    # Parse postgresql://user:pass@host/db?sslmode=require
    from urllib.parse import urlparse
    p = urlparse(connection_uri)
    try:
        conn = pg8000.native.Connection(
            user=p.username,
            password=p.password,
            host=p.hostname,
            port=p.port or 5432,
            database=p.path.lstrip("/").split("?")[0],
            ssl_context=True,
        )
    except Exception as e:
        print(f"  [Neon] Connection failed: {e}")
        return False

    try:
        # Strip all SQL comments (full-line and inline), then split on semicolons.
        # Removing inline comments first avoids splitting on ";" inside comments.
        no_comments = re.sub(r'--[^\n]*', '', sql)
        clean_lines = [
            ln for ln in no_comments.splitlines()
            if ln.strip()
        ]
        clean_sql = "\n".join(clean_lines)
        statements = [s.strip() for s in clean_sql.split(";") if s.strip()]
        for stmt in statements:
            conn.run(stmt)
        print(f"  [Neon] Ran {len(statements)} SQL statements OK")
        return True
    except Exception as e:
        print(f"  [Neon] SQL error: {e}")
        return False
    finally:
        conn.close()


# ── Supabase (shared-project mode) ────────────────────────────────────────────

def supabase_run_sql(sql: str) -> bool:
    """Executes SQL against Supabase via the Management API SQL endpoint."""
    ref = SUPABASE_URL.replace("https://", "").split(".")[0]
    url = f"https://api.supabase.com/v1/projects/{ref}/database/query"
    payload = json.dumps({"query": sql}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {SUPABASE_SVC_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"  [Supabase] SQL executed OK ({resp.status})")
            return True
    except urllib.error.HTTPError as e:
        print(f"  [Supabase] SQL error {e.code}: {e.read().decode(errors='replace')}")
        return False


# ── Provider dispatch ─────────────────────────────────────────────────────────

def provision_database(repo_name: str, schema_sql: Optional[str], app_url: str = "") -> dict:
    """Provisions the DB for a new app. Returns env vars for Vercel.
    Returns {} if no DB needed."""
    if not schema_sql:
        print("  No database needed for this app")
        return {}

    if DB_PROVIDER == "neon":
        print("  [Neon] Creating isolated project...")
        proj = neon_create_project(repo_name)
        if not proj:
            print("[ERROR] Neon project creation failed")
            sys.exit(1)
        print(f"  [Neon] Project: {proj['project_id']}")

        print("  [Neon] Running schema SQL...")
        if not neon_run_sql(proj["connection_uri"], schema_sql):
            print("[ERROR] Schema SQL failed on Neon")
            sys.exit(1)

        auth_secret = secrets.token_hex(32)
        if not app_url:
            app_url = f"https://{repo_name}.vercel.app"

        # Persist for the update flow
        registry_save(repo_name, {
            "provider": "neon",
            "project_id": proj["project_id"],
            "branch_id": proj["branch_id"],
            "db_name": proj["db_name"],
            "connection_uri": proj["connection_uri"],
        })

        return {
            "DATABASE_URL": proj["connection_uri"],
            "AUTH_SECRET": auth_secret,
            "NEXT_PUBLIC_APP_URL": app_url,
        }

    elif DB_PROVIDER == "supabase":
        print("  [Supabase] Running schema SQL on shared project...")
        if not supabase_run_sql(schema_sql):
            print("[ERROR] Schema SQL failed on Supabase")
            sys.exit(1)
        registry_save(repo_name, {"provider": "supabase"})
        return {
            "VITE_SUPABASE_URL": SUPABASE_URL,
            "VITE_SUPABASE_ANON_KEY": SUPABASE_ANON_KEY,
        }

    return {}


def run_migration(repo_name: str, migration_sql: Optional[str]) -> bool:
    """Runs a migration for the update flow against the app's existing DB."""
    if not migration_sql:
        print("  No database migration needed")
        return True

    info = registry_get(repo_name)
    provider = info.get("provider", DB_PROVIDER)

    if provider == "neon":
        conn_uri = info.get("connection_uri")
        if not conn_uri:
            print(f"[ERROR] No stored Neon connection for {repo_name}")
            return False
        return neon_run_sql(conn_uri, migration_sql)
    elif provider == "supabase":
        return supabase_run_sql(migration_sql)
    return False


# ── GitHub ────────────────────────────────────────────────────────────────────

def github_repo_exists(repo_name: str) -> bool:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{repo_name}"
    req = urllib.request.Request(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError as e:
        return e.code != 404


def github_create_repo(repo_name: str, description: str) -> bool:
    payload = json.dumps({
        "name": repo_name,
        "description": description,
        "private": False,
        "auto_init": False,
    }).encode()
    req = urllib.request.Request(
        "https://api.github.com/user/repos",
        data=payload,
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except urllib.error.HTTPError as e:
        print(f"  [GitHub] Create repo error {e.code}: {e.read().decode()}")
        return False


def git_push(repo_dir: Path, repo_name: str, commit_msg: str) -> bool:
    remote = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_OWNER}/{repo_name}.git"
    cmds = [
        ["git", "-C", str(repo_dir), "init"],
        ["git", "-C", str(repo_dir), "add", "-A"],
        ["git", "-C", str(repo_dir), "commit", "-m", commit_msg],
        ["git", "-C", str(repo_dir), "branch", "-M", "main"],
        ["git", "-C", str(repo_dir), "remote", "add", "origin", remote],
        ["git", "-C", str(repo_dir), "push", "-u", "origin", "main", "--force"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            # remote add fails if already exists — that's OK
            if "remote origin already exists" not in result.stderr:
                print(f"  [git] Error: {result.stderr.strip()}")
                return False
    return True


def git_push_update(repo_dir: Path, commit_msg: str) -> bool:
    remote_url = subprocess.run(
        ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
        capture_output=True, text=True
    ).stdout.strip()
    # Inject token into remote URL
    authed = remote_url.replace("https://", f"https://{GITHUB_TOKEN}@")
    subprocess.run(["git", "-C", str(repo_dir), "remote", "set-url", "origin", authed])

    cmds = [
        ["git", "-C", str(repo_dir), "add", "-A"],
        ["git", "-C", str(repo_dir), "commit", "-m", commit_msg],
        ["git", "-C", str(repo_dir), "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            print(f"  [git] Error: {result.stderr.strip()}")
            return False
    return True


# ── Vercel ────────────────────────────────────────────────────────────────────

def vercel_headers():
    h = {"Authorization": f"Bearer {VERCEL_TOKEN}", "Content-Type": "application/json"}
    return h


def vercel_request(method: str, path: str, payload: dict | None = None) -> dict | None:
    base = "https://api.vercel.com"
    url = f"{base}{path}"
    if VERCEL_TEAM_ID:
        url += ("&" if "?" in url else "?") + f"teamId={VERCEL_TEAM_ID}"
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, headers=vercel_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  [Vercel] {method} {path} → {e.code}: {e.read().decode()}")
        return None


def vercel_get_project(repo_name: str) -> dict | None:
    result = vercel_request("GET", f"/v9/projects/{repo_name}")
    return result


def vercel_create_project(repo_name: str, description: str) -> dict | None:
    payload = {
        "name": repo_name,
        "framework": "nextjs",
        "gitRepository": {
            "type": "github",
            "repo": f"{GITHUB_OWNER}/{repo_name}",
        },
        "publicSource": True,
    }
    return vercel_request("POST", "/v10/projects", payload)


def vercel_set_env(project_id: str, key: str, value: str):
    payload = [{"key": key, "value": value, "type": "plain", "target": ["production", "preview"]}]
    vercel_request("POST", f"/v10/projects/{project_id}/env", payload)


def vercel_disable_protection(project_id: str):
    """Disables Vercel Deployment Protection so the app is publicly accessible
    (otherwise every visitor gets a 401 Vercel SSO wall)."""
    vercel_request("PATCH", f"/v9/projects/{project_id}", {"ssoProtection": None})


def vercel_prod_domains(repo_name: str) -> list[str]:
    """Returns the project's production *.vercel.app domains."""
    result = vercel_request("GET", f"/v9/projects/{repo_name}")
    if result:
        aliases = ((result.get("targets") or {}).get("production") or {}).get("alias") or []
        doms = [a for a in aliases if isinstance(a, str) and a.endswith(".vercel.app")]
        if doms:
            return doms
    return [f"{repo_name}.vercel.app"]


def vercel_wait_for_deployment(repo_name: str, max_wait: int = 180) -> str | None:
    """Polls Vercel for a successful deployment, returns the URL."""
    print("  [Vercel] Waiting for deployment", end="", flush=True)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        result = vercel_request("GET", f"/v6/deployments?projectId={repo_name}&limit=1&state=READY")
        if result and result.get("deployments"):
            dep = result["deployments"][0]
            if dep.get("state") == "READY":
                url = dep.get("url", "")
                print(f"\n  [Vercel] Deployed: https://{url}")
                return f"https://{url}"
        print(".", end="", flush=True)
        time.sleep(10)
    print("\n  [Vercel] Timeout waiting for deployment")
    return None


# ── Write files ───────────────────────────────────────────────────────────────

def write_files(files: dict[str, str], dest: Path):
    for filepath, content in files.items():
        target = dest / filepath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"  [files] Wrote {filepath}")


def write_env_file(dest: Path, env_vars: dict):
    """Write .env.local with the app's front-end env vars for local dev (gitignored)."""
    if env_vars:
        content = "".join(f"{k}={v}\n" for k, v in env_vars.items())
        (dest / ".env.local").write_text(content)

    gitignore = dest / ".gitignore"
    ignores = "\n.env.local\nnode_modules/\n.next/\n"
    if gitignore.exists():
        if ".env.local" not in gitignore.read_text():
            gitignore.write_text(gitignore.read_text() + ignores)
    else:
        gitignore.write_text(ignores)


# ── Repo name extraction ──────────────────────────────────────────────────────

def extract_repo_name(ao_dir: Path, tg_user_id: str) -> str | None:
    """Tries to find the repo name from ao output markdown."""
    pattern = re.compile(r'app-tg[\w-]+-[\w-]+')
    for md_file in sorted(ao_dir.glob("**/*.md")):
        text = md_file.read_text(encoding="utf-8", errors="replace")
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


# ── Custom domain helpers ─────────────────────────────────────────────────────

def slug_from_repo(repo_name: str, tg_user_id: str) -> str:
    prefix = f"app-tg{tg_user_id}-"
    return repo_name[len(prefix):] if repo_name.startswith(prefix) else repo_name.split("-")[-1]


def cloudflare_add_cname(subdomain: str) -> bool:
    if not CLOUDFLARE_API_TOKEN or not CLOUDFLARE_ZONE_ID:
        return False
    payload = json.dumps({
        "type": "CNAME",
        "name": subdomain,
        "content": "cname.vercel-dns.com",
        "ttl": 1,
        "proxied": False,
    }).encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/zones/{CLOUDFLARE_ZONE_ID}/dns_records",
        data=payload,
        headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            ok = result.get("success", False)
            if ok:
                print(f"  [Cloudflare] CNAME {subdomain}.{CUSTOM_DOMAIN_BASE} → cname.vercel-dns.com created")
            return ok
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if "81057" in body or "already exists" in body.lower():
            print(f"  [Cloudflare] CNAME already exists — reusing")
            return True
        print(f"  [Cloudflare] CNAME error {e.code}: {body[:200]}")
        return False


def vercel_add_domain(project_id: str, domain: str) -> bool:
    result = vercel_request("POST", f"/v10/projects/{project_id}/domains", {"name": domain})
    if result:
        print(f"  [Vercel] Custom domain added: {domain}")
        return True
    return False


def take_screenshot(url: str, out_path: Path) -> bool:
    # Try Python playwright
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.screenshot(path=str(out_path))
            browser.close()
            return True
    except ImportError:
        pass
    except Exception as e:
        print(f"  [Screenshot] playwright error: {e}")
    # Fallback: npx playwright
    try:
        result = subprocess.run(
            ["npx", "playwright", "screenshot", "--browser", "chromium", url, str(out_path)],
            capture_output=True, text=True, timeout=45
        )
        return out_path.exists() and result.returncode == 0
    except Exception as e:
        print(f"  [Screenshot] npx fallback failed: {e}")
        return False


def write_readme(dest: Path, repo_name: str, description: str, live_url: str, has_db: bool):
    title = repo_name.split("-", 3)[-1].replace("-", " ").title() if "-" in repo_name else repo_name
    stack = "- Next.js 14 App Router · Neon Postgres · Better Auth" if has_db else "- Next.js 14 App Router (no database)"
    content = (
        f"# {title}\n\n"
        f"{description}\n\n"
        f"## Live App\n\n"
        f"{live_url}\n\n"
        f"## Stack\n\n"
        f"{stack}\n"
        f"- Deployed to Vercel\n\n"
        f"*Built with [Hermes App Builder](https://github.com/terenceng81/hermes)*\n"
    )
    (dest / "README.md").write_text(content)


# ── Main flows ────────────────────────────────────────────────────────────────

def flow_create(ao_dir: Path, tg_user_id: str, repo_name_arg: Optional[str] = None,
                description: str = ""):
    print(f"\n=== CREATE FLOW ===")
    print(f"ao output: {ao_dir}")

    # 1. Parse ao output
    print("\n[1] Parsing ao output...")
    files = parse_ao_output(ao_dir)
    if not files:
        print("[ERROR] No code files found in ao output. Check the ao run completed successfully.")
        sys.exit(1)
    print(f"  Found {len(files)} files: {list(files.keys())}")

    schema_sql = extract_schema_sql(ao_dir)
    has_db = schema_sql is not None
    if not has_db:
        print("  No schema.sql in ao output — app will have no database")

    # 2. Determine repo name (explicit arg > app-tg pattern in output > prompt)
    repo_name = repo_name_arg or extract_repo_name(ao_dir, tg_user_id)
    if not repo_name:
        slug = input("Could not detect repo name from ao output. Enter slug (e.g. budget): ").strip()
        repo_name = f"app-tg{tg_user_id.replace('_','')}-{slug}"
    print(f"\n[2] Repo name: {repo_name}")

    # Compute custom domain upfront (deterministic from repo name)
    app_slug = slug_from_repo(repo_name, tg_user_id)
    custom_domain = f"{app_slug}.{CUSTOM_DOMAIN_BASE}" if CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID else ""
    canonical_url = f"https://{custom_domain}" if custom_domain else f"https://{repo_name}.vercel.app"
    print(f"  Canonical URL: {canonical_url}")

    # 3. Provision database ({DB_PROVIDER}) — returns front-end env vars
    print(f"\n[3] Provisioning database (provider: {DB_PROVIDER})...")
    app_env = provision_database(repo_name, schema_sql, app_url=canonical_url)

    # 4. Write files to temp dir
    print("\n[4] Writing project files...")
    tmpdir = Path(tempfile.mkdtemp(prefix=f"{repo_name}-"))
    write_files(files, tmpdir)
    write_readme(tmpdir, repo_name, description or repo_name, canonical_url, has_db)
    write_env_file(tmpdir, app_env)

    # 5. Create GitHub repo
    print(f"\n[5] Creating GitHub repo: {GITHUB_OWNER}/{repo_name}")
    if github_repo_exists(repo_name):
        print("  Repo already exists, will push to it")
    else:
        if not github_create_repo(repo_name, f"Built by App Builder via Telegram"):
            sys.exit(1)
        time.sleep(2)  # let GitHub settle

    # 6. Git push
    print(f"\n[6] Pushing to GitHub...")
    if not git_push(tmpdir, repo_name, "feat: initial app generated by App Builder"):
        print("[ERROR] Git push failed")
        sys.exit(1)

    # 7. Create Vercel project
    print(f"\n[7] Setting up Vercel project...")
    project = vercel_get_project(repo_name)
    if project and project.get("id"):
        print(f"  Vercel project already exists: {project['id']}")
        project_id = project["id"]
    else:
        project = vercel_create_project(repo_name, "App Builder")
        if not project:
            print("[ERROR] Could not create Vercel project")
            sys.exit(1)
        project_id = project["id"]
        print(f"  Created Vercel project: {project_id}")

    # 8. Set env vars (from the provisioned database)
    print(f"\n[8] Setting Vercel env vars...")
    for key, value in app_env.items():
        vercel_set_env(project_id, key, value)
        print(f"  {key} set")

    # 7b. Add custom domain
    if custom_domain:
        print(f"\n[7b] Setting up custom domain: {custom_domain}")
        vercel_add_domain(project_id, custom_domain)
        cloudflare_add_cname(app_slug)

    # 8b. Make it publicly accessible
    print(f"\n[8b] Disabling deployment protection...")
    vercel_disable_protection(project_id)
    print("  Vercel deployment protection disabled (public)")

    # 9. Trigger redeploy (env var change doesn't auto-trigger, need a new deployment)
    print(f"\n[9] Triggering Vercel deployment...")
    vercel_request("POST", f"/v13/deployments", {
        "name": repo_name,
        "gitSource": {
            "type": "github",
            "org": GITHUB_OWNER,
            "repo": repo_name,
            "ref": "main",
        },
        "projectSettings": {"framework": "nextjs"},
    })

    # 10. Wait for deployment
    print(f"\n[10] Waiting for deployment...")
    live_url = vercel_wait_for_deployment(repo_name)

    # Cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)

    # 11. Screenshot + final output
    screenshot_path = ""
    if live_url:
        sc_path = Path(tempfile.gettempdir()) / f"screenshot-{repo_name}.png"
        # Try custom domain first, fall back to Vercel URL
        for sc_url in ([canonical_url, live_url] if custom_domain and canonical_url != live_url else [live_url]):
            print(f"\n[11] Taking screenshot of {sc_url}...")
            time.sleep(3)
            if take_screenshot(sc_url, sc_path):
                screenshot_path = str(sc_path)
                print(f"  [Screenshot] Saved: {screenshot_path}")
                break
            print(f"  [Screenshot] Failed for {sc_url}, trying fallback...")
        else:
            print("  [Screenshot] Skipped (playwright not available or all URLs failed)")

    print("\n" + "="*50)
    if live_url:
        print("SUCCESS")
        print(f"URL: {live_url}")
        if custom_domain:
            print(f"CUSTOM_URL: {canonical_url}")
        print(f"REPO: https://github.com/{GITHUB_OWNER}/{repo_name}")
        if screenshot_path:
            print(f"SCREENSHOT: {screenshot_path}")
    else:
        print("PARTIAL SUCCESS — deployment still in progress")
        print(f"REPO: https://github.com/{GITHUB_OWNER}/{repo_name}")
        print("Check Vercel dashboard for deployment URL")
    print("="*50)


def flow_update(ao_dir: Path, repo_dir: Path, tg_user_id: str):
    print(f"\n=== UPDATE FLOW ===")

    # 1. Parse ao output (only modified files)
    print("\n[1] Parsing ao output (modified files only)...")
    files = parse_ao_output(ao_dir)
    migration_sql = extract_migration_sql(ao_dir)
    repo_name = repo_dir.name

    # 2. Run migration SQL if needed (against this app's own DB)
    print("\n[2] Checking for database migration...")
    if not run_migration(repo_name, migration_sql):
        print("[ERROR] Migration SQL failed")
        sys.exit(1)

    # 3. Apply file changes
    print("\n[3] Applying file changes...")
    write_files(files, repo_dir)

    # Extract commit message from ao output
    commit_msg = "feat: update app via App Builder"
    for md_file in ao_dir.glob("**/*.md"):
        text = md_file.read_text()
        m = re.search(r'变更摘要[：:]\s*(.+)', text)
        if m:
            commit_msg = m.group(1).strip()
            break

    # 4. Push to GitHub
    print("\n[4] Pushing updates to GitHub...")
    if not git_push_update(repo_dir, commit_msg):
        sys.exit(1)

    # Vercel auto-redeploys on push — just wait
    print("\n[5] Waiting for Vercel to redeploy...")
    live_url = vercel_wait_for_deployment(repo_name)

    print("\n" + "="*50)
    print("UPDATE COMPLETE")
    if live_url:
        print(f"URL: {live_url}")
    print("CHANGE:", commit_msg)
    print("="*50)


# ── CLI ───────────────────────────────────────────────────────────────────────

def find_latest_ao_dir(pattern: str) -> Path | None:
    base = Path.home() / ".hermes" / "ao-output"
    matches = sorted(base.glob(f"{pattern}*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def main():
    parser = argparse.ArgumentParser(description="App Builder Deploy Script")
    parser.add_argument("--mode", choices=["create", "update"], default="create")
    parser.add_argument("--ao-output", help="Path to ao output directory")
    parser.add_argument("--repo-dir", help="(update mode) Path to cloned repo")
    parser.add_argument("--repo-name", help="(create mode) Explicit repo name, e.g. app-tg123-budget")
    parser.add_argument("--tg-user-id", required=True, help="Telegram user ID")
    parser.add_argument("--description", default="", help="Original app description (used for README)")
    args = parser.parse_args()

    check_env(args.mode)

    # Resolve ao output dir
    if args.ao_output:
        ao_dir = Path(args.ao_output).expanduser()
    else:
        pattern = "App Builder — Create" if args.mode == "create" else "App Builder — Update"
        ao_dir = find_latest_ao_dir(pattern)
        if not ao_dir:
            print(f"[ERROR] Could not find ao output dir. Run ao workflow first.")
            sys.exit(1)

    if not ao_dir.exists():
        print(f"[ERROR] ao output dir not found: {ao_dir}")
        sys.exit(1)

    if args.mode == "create":
        flow_create(ao_dir, args.tg_user_id, args.repo_name, description=args.description)
    else:
        if not args.repo_dir:
            print("[ERROR] --repo-dir required for update mode")
            sys.exit(1)
        flow_update(ao_dir, Path(args.repo_dir).expanduser(), args.tg_user_id)


if __name__ == "__main__":
    main()
