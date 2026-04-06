from pathlib import Path

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
