SERVICE = {
    "id": "wikijs",
    "name": "Wiki.js",
    "description": "Wiki with Git repository sync",
    "questions": [
        {"key": "WIKI_PORT",    "label": "External port",         "default": "3001"},
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
            "ports": ["${WIKI_PORT}:3000"],
            "depends_on": ["wikijs-db"],
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
    "post_install_note": (
        "ℹ  Wiki.js + Gitea sync: configure it from the Wiki.js admin panel\n"
        "   at Storage → Git Repository."
    ),
}
