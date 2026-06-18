#!/usr/bin/env python3
"""
finish-vercel.py — finish the Vercel half of a deploy that already has its
GitHub repo + Neon database provisioned (e.g. after installing the Vercel
GitHub App). Reuses deploy-app.py's functions and the app registry, so it
does NOT re-create the Neon project or GitHub repo.

Usage: python3 finish-vercel.py <repo_name>
"""
import importlib.util
import sys
import time
from pathlib import Path

DEPLOY = Path(__file__).with_name("deploy-app.py")
spec = importlib.util.spec_from_file_location("deploy_app", DEPLOY)
da = importlib.util.module_from_spec(spec)
spec.loader.exec_module(da)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 finish-vercel.py <repo_name>")
        sys.exit(1)
    repo = sys.argv[1]

    info = da.registry_get(repo)
    if not info:
        print(f"[ERROR] {repo} not in registry — run the full deploy first.")
        sys.exit(1)

    # Front-end env vars from the already-provisioned Neon project
    app_env = {}
    if info.get("data_api_url"):
        app_env["VITE_NEON_DATA_API_URL"] = info["data_api_url"]
    if info.get("auth_url"):
        app_env["VITE_NEON_AUTH_URL"] = info["auth_url"]
    print(f"[finish] {repo} — reusing Neon project {info.get('project_id')}")
    print(f"[finish] env vars: {list(app_env.keys())}")

    # 1. Create (or find) Vercel project linked to the existing GitHub repo
    print("\n[1] Setting up Vercel project...")
    project = da.vercel_get_project(repo)
    if project and project.get("id"):
        print(f"  Vercel project already exists: {project['id']}")
        project_id = project["id"]
    else:
        project = da.vercel_create_project(repo, "App Builder")
        if not project:
            print("[ERROR] Could not create Vercel project (is the Vercel GitHub App installed?)")
            sys.exit(1)
        project_id = project["id"]
        print(f"  Created Vercel project: {project_id}")

    # 2. Env vars
    print("\n[2] Setting Vercel env vars...")
    for key, value in app_env.items():
        da.vercel_set_env(project_id, key, value)
        print(f"  {key} set")

    # 2b. Public access + Neon Auth trusted domains
    print("\n[2b] Disabling protection + registering Neon Auth trusted domains...")
    da.vercel_disable_protection(project_id)
    print("  Vercel protection disabled")
    if app_env.get("VITE_NEON_AUTH_URL") and info.get("project_id") and info.get("branch_id"):
        for dom in da.vercel_prod_domains(repo):
            if da.neon_add_trusted_domain(info["project_id"], info["branch_id"], f"https://{dom}"):
                print(f"  Neon trusted domain added: https://{dom}")

    # 3. Trigger deployment from the GitHub repo's main branch
    print("\n[3] Triggering Vercel deployment...")
    da.vercel_request("POST", "/v13/deployments", {
        "name": repo,
        "gitSource": {"type": "github", "org": da.GITHUB_OWNER, "repo": repo, "ref": "main"},
        "projectSettings": {"framework": "vite"},
    })

    # 4. Wait for the URL
    print("\n[4] Waiting for deployment...")
    live_url = da.vercel_wait_for_deployment(repo)

    print("\n" + "=" * 50)
    if live_url:
        print("SUCCESS")
        print(f"URL: {live_url}")
    else:
        print("PARTIAL — deployment still building; check Vercel dashboard")
    print(f"REPO: https://github.com/{da.GITHUB_OWNER}/{repo}")
    print("=" * 50)


if __name__ == "__main__":
    main()
