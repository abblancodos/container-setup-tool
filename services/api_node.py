SERVICE = {
    "id": "api-node",
    "name": "API — Node.js",
    "description": "Node.js API container (deploy via Gitea Actions)",
    "questions": [
        {"key": "API_NODE_NAME",   "label": "Service name (e.g. my-api)", "default": "my-api"},
        {"key": "API_NODE_DOMAIN", "label": "Subdomain (e.g. api)",       "default": "api"},
    ],
    "compose": {
        "api-node": {
            "image": "${API_NODE_NAME}:latest",
            "restart": "unless-stopped",
            "container_name": "${API_NODE_NAME}",
            "healthcheck": {
                "test": ["CMD-SHELL", "wget -qO- http://localhost:3000/health || exit 1"],
                "interval": "15s",
                "timeout": "5s",
                "retries": 3,
            },
        }
    },
    "nginx_upstream":   "api-node:3000",
    "nginx_domain_var": "API_NODE_DOMAIN",
    "volumes": [],
    "post_install_note": (
        "ℹ  Deploy via Gitea Actions: push → runner builds image → docker compose up -d\n"
        "   Set STACK_DIR secret in Gitea repo settings."
    ),
}
