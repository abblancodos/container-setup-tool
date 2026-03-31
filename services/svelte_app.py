SERVICE = {
    "id": "svelte-app",
    "name": "Frontend — SvelteKit",
    "description": "SvelteKit frontend (deploy via Gitea Actions)",
    "questions": [
        {"key": "SVELTE_APP_NAME",   "label": "App name (e.g. dashboard)",   "default": "dashboard"},
        {"key": "SVELTE_APP_DOMAIN", "label": "Subdomain (e.g. dashboard)",   "default": "dashboard"},
        {"key": "SVELTE_API_URL",    "label": "Backend API URL (e.g. http://my-api:3000)", "default": ""},
    ],
    "compose": {
        "svelte-app": {
            "image": "${SVELTE_APP_NAME}:latest",
            "restart": "unless-stopped",
            "container_name": "${SVELTE_APP_NAME}",
            "environment": [
                "PUBLIC_API_URL=${SVELTE_API_URL}",
            ],
            "healthcheck": {
                "test": ["CMD-SHELL", "wget -qO- http://localhost:3000/ > /dev/null || exit 1"],
                "interval": "15s",
                "timeout": "5s",
                "retries": 3,
            },
        }
    },
    "nginx_upstream":   "svelte-app:3000",
    "nginx_domain_var": "SVELTE_APP_DOMAIN",
    "volumes": [],
    "post_install_note": (
        "ℹ  Deploy via Gitea Actions: push → runner builds image → docker compose up -d\n"
        "   Set STACK_DIR secret in Gitea repo settings."
    ),
}
