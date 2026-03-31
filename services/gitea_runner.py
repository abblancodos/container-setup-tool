SERVICE = {
    "id": "gitea-runner",
    "name": "Gitea Actions runner",
    "description": "CI/CD runner for Gitea Actions",
    "questions": [
        {"key": "RUNNER_TOKEN", "label": "Runner registration token (from Gitea Admin → Actions → Runners)", "default": "REPLACE_AFTER_GITEA_SETUP"},
    ],
    "compose": {
        "gitea-runner": {
            "image": "gitea/act_runner:latest",
            "restart": "unless-stopped",
            "environment": [
                "GITEA_INSTANCE_URL=http://gitea:3000",
                "GITEA_RUNNER_REGISTRATION_TOKEN=${RUNNER_TOKEN}",
            ],
            "volumes": [
                "./data/gitea-runner:/data",
                "/var/run/docker.sock:/var/run/docker.sock",
            ],
            "depends_on": ["gitea"],
        },
    },
    "nginx_upstream":   None,
    "nginx_domain_var": None,
    "volumes": ["./data/gitea-runner"],
    "post_install_note": (
        "⚠  Register the runner after Gitea is up:\n"
        "   Gitea Admin → Actions → Runners → New runner\n"
        "   Copy the token and update RUNNER_TOKEN in .env\n"
        "   Then: docker compose restart gitea-runner"
    ),
}
