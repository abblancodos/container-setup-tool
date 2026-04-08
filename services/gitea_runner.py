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
    "bootstrap": {
        "label": "Register Gitea Actions runner",
        "check_cmd": None,
        "note": (
            "Go to Gitea → Site Administration → Actions → Runners → Create new runner\n"
            "  Copy the registration token — you'll need it in the next step."
        ),
        "post_hook": lambda output_dir, env_vars: _runner_post_bootstrap(output_dir, env_vars),
    },
    "post_install_note": (
        "⚠  Register the runner after Gitea is up:\n"
        "   Gitea Admin → Actions → Runners → New runner\n"
        "   Then run setup.py → Bootstrap services → Gitea Actions runner"
    ),
}


def _runner_post_bootstrap(output_dir, env_vars):
    import questionary as q
    token = q.text(
        "Paste the runner registration token from Gitea:",
        validate=lambda v: True if v.strip() else "Token cannot be empty",
    ).ask()
    if not token:
        return [("warn", "No token provided — runner not started")]

    # Actualizar RUNNER_TOKEN en .env
    env_file = output_dir / ".env"
    content  = env_file.read_text()
    if "RUNNER_TOKEN=" in content:
        import re
        content = re.sub(r"RUNNER_TOKEN=.*", f"RUNNER_TOKEN={token.strip()}", content)
    else:
        content += f"\nRUNNER_TOKEN={token.strip()}\n"
    env_file.write_text(content)

    # Levantar el runner
    import subprocess
    subprocess.run(
        ["docker", "compose", "--project-directory", str(output_dir), "up", "-d", "gitea-runner"],
        capture_output=True, cwd=output_dir,
    )
    return [
        ("ok", "RUNNER_TOKEN saved to .env"),
        ("ok", "gitea-runner started"),
    ]
