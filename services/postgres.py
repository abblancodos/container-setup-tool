SERVICE = {
    "id": "postgres",
    "name": "PostgreSQL",
    "description": "PostgreSQL database server",
    "questions": [
        {"key": "POSTGRES_USER", "label": "Username",      "default": "postgres"},
        {"key": "POSTGRES_PASS", "label": "Password",      "default": "changeme"},
        {"key": "POSTGRES_DB",   "label": "Database name", "default": "appdb"},
    ],
    "compose": {
        "postgres": {
            "image": "postgres:16-bookworm",
            "restart": "unless-stopped",
            "environment": [
                "POSTGRES_USER=${POSTGRES_USER}",
                "POSTGRES_PASSWORD=${POSTGRES_PASS}",
                "POSTGRES_DB=${POSTGRES_DB}",
            ],
            "volumes": ["./data/postgres:/var/lib/postgresql/data"],
            # No external port — internal only via infra network
            # To access from host: ssh tunnel or add ports: ["5433:5432"] manually
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5,
            },
        }
    },
    "nginx_upstream":   None,
    "nginx_domain_var": None,
    "volumes": ["./data/postgres"],
    "post_install_note": None,
}
