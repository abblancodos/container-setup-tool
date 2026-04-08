from pathlib import Path
import subprocess
import yaml


def _gitea_post_bootstrap(output_dir: Path, env_vars: dict):
    """Aplica config post-wizard: ROOT_URL, deshabilita registro, activa Actions."""
    gitea_domain  = env_vars.get("GITEA_DOMAIN", "git")
    base_domain   = env_vars.get("BASE_DOMAIN", "")
    root_url      = f"https://{gitea_domain}.{base_domain}/" if base_domain and base_domain != "localhost" \
                    else f"http://{gitea_domain}/"

    new_env_vars = [
        f"GITEA__server__ROOT_URL={root_url}",
        "GITEA__service__DISABLE_REGISTRATION=true",
        "GITEA__actions__ENABLED=true",
    ]

    # Leer el compose de gitea
    compose_path = output_dir / "docker-compose.gitea.yml"
    if not compose_path.exists():
        compose_path = output_dir / "docker-compose.yml"
    if not compose_path.exists():
        return [("warn", "Could not find gitea compose file — add env vars manually")]

    with open(compose_path) as f:
        data = yaml.safe_load(f)

    svc = data.get("services", {}).get("gitea")
    if not svc:
        return [("warn", "gitea service not found in compose")]

    existing_env = svc.get("environment", [])
    # Quitar vars que vamos a sobreescribir
    keys_to_replace = {v.split("=")[0] for v in new_env_vars}
    existing_env = [e for e in existing_env if e.split("=")[0] not in keys_to_replace]
    svc["environment"] = existing_env + new_env_vars

    with open(compose_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Reiniciar gitea
    subprocess.run(
        ["docker", "compose", "--project-directory", str(output_dir), "up", "-d", "gitea"],
        capture_output=True, cwd=output_dir,
    )
    return [
        ("ok", f"ROOT_URL set to {root_url}"),
        ("ok", "Registration disabled"),
        ("ok", "Actions enabled"),
        ("ok", "Gitea restarted"),
    ]


SERVICE = {
    "id": "gitea",
    "name": "Gitea",
    "description": "Self-hosted Git server",
    "questions": [
        {"key": "GITEA_DOMAIN",  "label": "Subdomain (e.g. git)",       "default": "git"},
        {"key": "GITEA_DB_PASS", "label": "Internal DB password",        "default": "gitea_secret"},
    ],
    "compose": {
        "gitea": {
            "image": "gitea/gitea:latest-rootless",
            "restart": "unless-stopped",
            "environment": [
                "GITEA__database__DB_TYPE=postgres",
                "GITEA__database__HOST=gitea-db:5432",
                "GITEA__database__NAME=gitea",
                "GITEA__database__USER=gitea",
                "GITEA__database__PASSWD=${GITEA_DB_PASS}",
            ],
            "volumes": ["./data/gitea:/var/lib/gitea"],
            "depends_on": ["gitea-db"],
            # No external port — accessed via nginx only
        },
        "gitea-db": {
            "image": "postgres:16-bookworm",
            "restart": "unless-stopped",
            "environment": [
                "POSTGRES_USER=gitea",
                "POSTGRES_PASSWORD=${GITEA_DB_PASS}",
                "POSTGRES_DB=gitea",
            ],
            "volumes": ["./data/gitea-db:/var/lib/postgresql/data"],
        },
    },
    "nginx_upstream":   "gitea:3000",
    "nginx_domain_var": "GITEA_DOMAIN",
    "domain_env_vars": {
        "GITEA__server__ROOT_URL": "https://{subdomain}.{base_domain}/",
    },
    "volumes": ["./data/gitea", "./data/gitea-db"],
    "bootstrap": {
        "label": "Complete Gitea install wizard",
        "check_cmd": ["docker", "exec", "server-lab-gitea-1",
                      "grep", "-q", "INSTALL_LOCK.*true", "/etc/gitea/app.ini"],
        "note": (
            "Open http://{server_ip} in your browser and complete the wizard.\n"
            "  • Database host: gitea-db:5432\n"
            "  • Database name: gitea\n"
            "  • Base URL: set to your final domain if known, or the server IP for now."
        ),
        "post_hook": lambda output_dir, env_vars: _gitea_post_bootstrap(output_dir, env_vars),
    },
    "post_create_hook": lambda data_dir: [
        # gitea:latest-rootless runs as UID 1000 — fix permissions on data dir
        ["sudo", "chown", "-R", "1000:1000", str(Path(data_dir) / "gitea")],
    ],
    "post_install_note": (
        "ℹ  Open Gitea via nginx to complete the install wizard.\n"
        "   Point your Caddy/Cloudflare domain to this server."
    ),
}
