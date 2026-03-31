SERVICE = {
    "id": "api-rust",
    "name": "API — Rust/Axum",
    "description": "Rust/Axum API container (deploy via Gitea Actions)",
    "questions": [
        {"key": "API_RUST_NAME",   "label": "Service name (e.g. sensor-api)", "default": "sensor-api"},
        {"key": "API_RUST_DOMAIN", "label": "Subdomain (e.g. sensor)",        "default": "sensor"},
    ],
    "compose": {
        "${API_RUST_NAME}": {
            "image": "${API_RUST_NAME}:latest",
            "restart": "unless-stopped",
            # No external port — accessed via nginx only
            "healthcheck": {
                "test": ["CMD-SHELL", "curl -f http://localhost:3000/health || exit 1"],
                "interval": "15s",
                "timeout": "5s",
                "retries": 3,
            },
        }
    },
    "nginx_upstream":   "${API_RUST_NAME}:3000",
    "nginx_domain_var": "API_RUST_DOMAIN",
    "volumes": [],
    "post_install_note": (
        "ℹ  Deploy via Gitea Actions: push → runner builds image → docker compose up -d\n"
        "   Set STACK_DIR secret in Gitea repo settings."
    ),
}
