SERVICE = {
    "id": "gitea",
    "name": "Gitea + Actions runner",
    "description": "Self-hosted Git server with CI/CD",
    "questions": [
        {"key": "GITEA_PORT",    "label": "Gitea external port",          "default": "3000"},
        {"key": "GITEA_DOMAIN",  "label": "Subdomain (e.g. git)",         "default": "git"},
        {"key": "GITEA_DB_PASS", "label": "Internal database password",   "default": "gitea_secret"},
    ],
    "compose": {
        "gitea": {
            "image": "gitea/gitea:latest",
            "restart": "unless-stopped",
            "environment": [
                "GITEA__database__DB_TYPE=postgres",
                "GITEA__database__HOST=gitea-db:5432",
                "GITEA__database__NAME=gitea",
                "GITEA__database__USER=gitea",
                "GITEA__database__PASSWD=${GITEA_DB_PASS}",
            ],
            "volumes": ["./data/gitea:/data"],
            "ports": ["${GITEA_PORT}:3000"],
            "depends_on": ["gitea-db"],
        },
        "gitea-db": {
            "image": "postgres:16-alpine",
            "restart": "unless-stopped",
            "environment": [
                "POSTGRES_USER=gitea",
                "POSTGRES_PASSWORD=${GITEA_DB_PASS}",
                "POSTGRES_DB=gitea",
            ],
            "volumes": ["./data/gitea-db:/var/lib/postgresql/data"],
        },
        "gitea-runner": {
            "image": "gitea/act_runner:latest",
            "restart": "unless-stopped",
            "environment": [
                "GITEA_INSTANCE_URL=http://gitea:3000",
                "GITEA_RUNNER_REGISTRATION_TOKEN=REPLACE_AFTER_SETUP",
            ],
            "volumes": [
                "./data/gitea-runner:/data",
                "/var/run/docker.sock:/var/run/docker.sock",
            ],
            "depends_on": ["gitea"],
        },
    },
    "nginx_upstream":   "gitea:3000",
    "nginx_domain_var": "GITEA_DOMAIN",
    "volumes": ["./data/gitea", "./data/gitea-db", "./data/gitea-runner"],
    "post_install_note": (
        "⚠  Gitea runner: after your first login, generate a token at\n"
        "   Admin → Actions → Runners and replace REPLACE_AFTER_SETUP in .env"
    ),
}
