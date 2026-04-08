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
    import subprocess
    import yaml
    import re
    from pathlib import Path

    # Detectar todos los servicios de tipo gitea runner en los composes
    runner_services = []
    for cf in sorted(output_dir.glob("docker-compose*.yml")):
        data = yaml.safe_load(cf.read_text()) or {}
        for svc_name, svc_def in (data.get("services") or {}).items():
            image = svc_def.get("image", "")
            if "act_runner" in image:
                runner_services.append(svc_name)

    if not runner_services:
        return [("warn", "No gitea runner services found in compose files")]

    # Si hay más de uno, preguntar cuál configurar
    if len(runner_services) == 1:
        selected = [runner_services[0]]
    else:
        selected = q.checkbox(
            "Multiple runners found — select which to register:",
            choices=[q.Choice(s, value=s, checked=True) for s in runner_services],
        ).ask() or []
        if not selected:
            return [("warn", "No runners selected")]

    results = []
    for runner in selected:
        token = q.text(
            f"Paste the registration token for [{runner}] (Gitea → Site Admin → Actions → Runners):",
            validate=lambda v: True if v.strip() else "Token cannot be empty",
        ).ask()
        if not token:
            results.append(("warn", f"{runner}: no token provided — skipped"))
            continue

        # Guardar token con clave única por runner
        token_key = f"RUNNER_TOKEN_{runner.upper().replace('-', '_')}"
        env_file  = Path(output_dir) / ".env"
        content   = env_file.read_text()
        if token_key in content:
            content = re.sub(rf"{token_key}=.*", f"{token_key}={token.strip()}", content)
        else:
            content += f"\n{token_key}={token.strip()}\n"
        # También actualizar RUNNER_TOKEN genérico si es el primero
        if runner == selected[0]:
            if "RUNNER_TOKEN=" in content:
                content = re.sub(r"(?<![_A-Z])RUNNER_TOKEN=.*", f"RUNNER_TOKEN={token.strip()}", content)
            else:
                content += f"\nRUNNER_TOKEN={token.strip()}\n"
        env_file.write_text(content)

        # Levantar el runner
        subprocess.run(
            ["docker", "compose", "--project-directory", str(output_dir),
             "up", "-d", runner],
            capture_output=True, cwd=output_dir,
        )
        results.append(("ok", f"{runner} registered and started"))

    return results
