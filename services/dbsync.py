SERVICE = {
    "id": "dbsync",
    "name": "DBSync engine + frontend",
    "description": "PostgreSQL sync engine with admin panel",
    "repo_url": "infra/dbsync-engine",      # cloned from {GITEA_BASE}/infra/dbsync-engine
    "questions": [
        {"key": "DBSYNC_API_PORT",      "label": "API port (Rust/Axum)",          "default": "4000"},
        {"key": "DBSYNC_FRONTEND_PORT", "label": "Frontend port (SvelteKit)",      "default": "4001"},
        {"key": "DBSYNC_DOMAIN",        "label": "Frontend subdomain (e.g. sync)", "default": "sync"},
        {"key": "DBSYNC_REPLICA_PASS",  "label": "Local replica DB password",      "default": "sync_secret"},
        {"key": "DBSYNC_BUILD_TARGET",  "label": "Build target (dev or prod)",     "default": "prod"},
    ],
    "compose": {
        "dbsync-db": {
            "image": "postgres:16-alpine",
            "restart": "unless-stopped",
            "environment": [
                "POSTGRES_USER=dbsync",
                "POSTGRES_PASSWORD=${DBSYNC_REPLICA_PASS}",
                "POSTGRES_DB=replica",
            ],
            "volumes": ["./data/dbsync-db:/var/lib/postgresql/data"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U dbsync -d replica"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5,
            },
        },
        "dbsync-engine": {
            "build": {
                "context": "./services/dbsync",
                "dockerfile": "Dockerfile.engine",
                "target": "${DBSYNC_BUILD_TARGET}",
            },
            "restart": "unless-stopped",
            "environment": [
                "DATABASE_URL=postgres://dbsync:${DBSYNC_REPLICA_PASS}@dbsync-db:5432/replica",
                "CONFIG_PATH=/etc/dbsync/config.toml",
            ],
            "volumes": ["./config/dbsync.toml:/etc/dbsync/config.toml"],
            "ports": ["${DBSYNC_API_PORT}:3000"],
            "depends_on": {"dbsync-db": {"condition": "service_healthy"}},
            "healthcheck": {
                "test": ["CMD-SHELL", "curl -f http://localhost:3000/health || exit 1"],
                "interval": "15s",
                "timeout": "5s",
                "retries": 3,
            },
        },
        "dbsync-frontend": {
            "build": {
                "context": "./services/dbsync",
                "dockerfile": "Dockerfile.frontend",
                "target": "${DBSYNC_BUILD_TARGET}",
            },
            "restart": "unless-stopped",
            "environment": ["PUBLIC_API_URL=http://dbsync-engine:3000"],
            "ports": ["${DBSYNC_FRONTEND_PORT}:5173"],
            "depends_on": {"dbsync-engine": {"condition": "service_healthy"}},
        },
    },
    "nginx_upstream":   "dbsync-frontend:5173",
    "nginx_domain_var": "DBSYNC_DOMAIN",
    "volumes": ["./data/dbsync-db"],
    "post_install_note": (
        "ℹ  Edit ./config/dbsync.toml to add sync peers before running docker compose up"
    ),
}
