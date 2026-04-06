from pathlib import Path

SERVICE = {
    "id": "wikijs",
    "name": "Wiki.js",
    "description": "Wiki with Git repository sync",
    "questions": [
        {"key": "WIKI_DOMAIN",  "label": "Subdomain (e.g. wiki)", "default": "wiki"},
        {"key": "WIKI_DB_PASS", "label": "Internal DB password",  "default": "wiki_secret"},
    ],
    "compose": {
        "wikijs": {
            "image": "ghcr.io/requarks/wiki:2",
            "restart": "unless-stopped",
            "environment": [
                "DB_TYPE=postgres",
                "DB_HOST=wikijs-db",
                "DB_PORT=5432",
                "DB_NAME=wiki",
                "DB_USER=wiki",
                "DB_PASS=${WIKI_DB_PASS}",
            ],
            "volumes": ["./data/wikijs:/wiki/data"],
            "depends_on": ["wikijs-db"],
            # No external port — accessed via nginx only
        },
        "wikijs-db": {
            "image": "postgres:16-bookworm",
            "restart": "unless-stopped",
            "environment": [
                "POSTGRES_USER=wiki",
                "POSTGRES_PASSWORD=${WIKI_DB_PASS}",
                "POSTGRES_DB=wiki",
            ],
            "volumes": ["./data/wikijs-db:/var/lib/postgresql/data"],
        },
    },
    "nginx_upstream":   "wikijs:3000",
    "nginx_domain_var": "WIKI_DOMAIN",
    "volumes": ["./data/wikijs", "./data/wikijs-db"],
    "bootstrap": {
        "label": "Complete Wiki.js setup wizard",
        "check_cmd": None,
        "note": (
            "Open http://{server_ip} in your browser and complete the setup.\n"
            "  • Database: PostgreSQL, host wikijs-db:5432, db: wiki, user: wiki\n"
            "  • Create an admin account when prompted."
        ),
    },
    "post_create_hook": lambda data_dir: [
        ["sudo", "chown", "-R", "1000:1000", str(Path(data_dir) / "wikijs")],
    ],
    "post_install_note": (
        "ℹ  Wiki.js + Gitea sync: configure at Storage → Git Repository."
    ),
}
