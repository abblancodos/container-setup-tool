SERVICE = {
    "id": "postgres",
    "name": "PostgreSQL (standalone)",
    "description": "Standalone PostgreSQL database",
    "questions": [
        {"key": "POSTGRES_PORT", "label": "External port",     "default": "5432"},
        {"key": "POSTGRES_USER", "label": "Username",          "default": "postgres"},
        {"key": "POSTGRES_PASS", "label": "Password",          "default": "changeme"},
        {"key": "POSTGRES_DB",   "label": "Database name",     "default": "appdb"},
    ],
    "compose": {
        "postgres": {
            "image": "postgres:16-alpine",
            "restart": "unless-stopped",
            "environment": [
                "POSTGRES_USER=${POSTGRES_USER}",
                "POSTGRES_PASSWORD=${POSTGRES_PASS}",
                "POSTGRES_DB=${POSTGRES_DB}",
            ],
            "volumes": ["./data/postgres:/var/lib/postgresql/data"],
            "ports": ["${POSTGRES_PORT}:5432"],
        }
    },
    "nginx_upstream":   None,
    "nginx_domain_var": None,
    "volumes": ["./data/postgres"],
    "post_install_note": None,
}
