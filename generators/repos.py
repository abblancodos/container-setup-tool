"""
generators/repos.py

Clones or pulls service repos that have a repo_url field.
The URL is assembled as: {gitea_base}/{repo_url}
  e.g. repo_url = "infra/dbsync-engine"
       gitea_base = "https://git.myserver.com"
       → clones https://git.myserver.com/infra/dbsync-engine
         into   {output_dir}/services/dbsync-engine/
"""

import subprocess
from pathlib import Path


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    result = subprocess.run(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.returncode, result.stdout.strip()


def clone_service_repos(
    selected_services: list[dict],
    gitea_base: str,
    output_dir: Path,
) -> list[dict]:
    """
    For each service with a repo_url field, clone or pull the repo.

    Returns a list of result dicts:
      {"service": id, "status": "cloned"|"pulled"|"skipped"|"error", "detail": str}
    """
    gitea_base = gitea_base.rstrip("/")
    services_dir = output_dir / "services"
    services_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for svc in selected_services:
        repo_url = svc.get("repo_url")
        if not repo_url:
            continue  # public image, nothing to clone

        full_url  = f"{gitea_base}/{repo_url}"
        target    = services_dir / svc["id"]

        if target.exists() and (target / ".git").exists():
            # Already cloned — pull latest instead
            code, out = _run(["git", "pull", "--ff-only"], cwd=target)
            if code == 0:
                results.append({"service": svc["id"], "status": "pulled", "detail": out})
            else:
                results.append({"service": svc["id"], "status": "error",  "detail": out})
        elif target.exists():
            # Directory exists but not a git repo — skip to avoid overwriting
            results.append({
                "service": svc["id"],
                "status":  "skipped",
                "detail":  f"{target} exists but is not a git repo — skipping",
            })
        else:
            code, out = _run(["git", "clone", full_url, str(target)])
            if code == 0:
                results.append({"service": svc["id"], "status": "cloned", "detail": out})
            else:
                results.append({"service": svc["id"], "status": "error",  "detail": out})

    return results


def services_needing_clone(selected_services: list[dict]) -> list[dict]:
    """Return only services that have a repo_url (i.e. need cloning)."""
    return [s for s in selected_services if s.get("repo_url")]
