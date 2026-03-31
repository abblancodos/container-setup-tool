import questionary
import yaml
from pathlib import Path


def ask_custom_template(templates_dir: Path) -> dict | None:
    """Guide the user through creating a custom service template."""

    choice = questionary.select(
        "Use an existing template or create a new one?",
        choices=[
            questionary.Choice("Create new template", value="new"),
            questionary.Choice("Cancel", value="cancel"),
        ],
    ).ask()

    if choice == "cancel" or choice is None:
        return None

    print()
    print("  A few questions to build the template.")
    print("  Leave fields blank if they don't apply.\n")

    svc_id = questionary.text(
        "Service ID (no spaces, e.g. myapp):",
        validate=lambda v: True if v.strip() else "Cannot be empty",
    ).ask()

    svc_name = questionary.text("Display name:").ask()
    svc_desc = questionary.text("Short description:").ask()
    image    = questionary.text(
        "Docker image (e.g. nginx:alpine, myuser/myapp:latest):",
        validate=lambda v: True if v.strip() else "Required",
    ).ask()

    ext_port = questionary.text(
        "Container port to expose (e.g. 3000), leave blank if none:",
    ).ask()

    needs_nginx = False
    subdomain   = ""
    if ext_port:
        needs_nginx = questionary.confirm(
            "Should nginx proxy to this service?", default=True
        ).ask()
        if needs_nginx:
            subdomain = questionary.text(
                "Default subdomain (e.g. myapp):", default=svc_id
            ).ask()

    volumes_raw   = questionary.text(
        "Volumes to mount (comma-separated, e.g. ./data/myapp:/data):\n  blank = none:",
    ).ask()
    env_vars_raw  = questionary.text(
        "Container environment variables (comma-separated, e.g. ENV=val,OTHER=x):\n  blank = none:",
    ).ask()
    extra_q_raw   = questionary.text(
        "User-configurable variables (comma-separated keys, e.g. MY_SECRET,MY_PORT):\n  blank = none:",
    ).ask()
    depends_raw   = questionary.text(
        "Depends on another service in this stack? (e.g. postgres, blank = no):",
    ).ask()
    template_note = questionary.text(
        "Post-install note (special instructions, blank = none):",
    ).ask()

    volumes_list  = [v.strip() for v in volumes_raw.split(",")  if v.strip()] if volumes_raw  else []
    env_vars_list = [e.strip() for e in env_vars_raw.split(",") if e.strip()] if env_vars_raw else []
    depends_list  = [d.strip() for d in depends_raw.split(",")  if d.strip()] if depends_raw  else []
    extra_keys    = [k.strip() for k in extra_q_raw.split(",")  if k.strip()] if extra_q_raw  else []

    questions = []
    for key in extra_keys:
        default_val = questionary.text(f"  Default value for {key}:").ask()
        label       = questionary.text(f"  Description for {key}:").ask()
        questions.append({"key": key, "label": label, "default": default_val})

    compose_def: dict = {"image": image, "restart": "unless-stopped"}
    if env_vars_list:
        compose_def["environment"] = env_vars_list
    if volumes_list:
        compose_def["volumes"] = volumes_list
    if ext_port:
        port_key = f"{svc_id.upper().replace('-', '_')}_PORT"
        compose_def["ports"] = [f"${{{port_key}}}:{ext_port}"]
        if not any(q["key"] == port_key for q in questions):
            questions.insert(0, {"key": port_key, "label": "External port", "default": ext_port})
    if depends_list:
        compose_def["depends_on"] = depends_list

    data_volumes = [f"./data/{svc_id}"] if any("./data" in v for v in volumes_list) else []

    SERVICE = {
        "id":               svc_id,
        "name":             svc_name,
        "description":      svc_desc,
        "questions":        questions,
        "compose":          {svc_id: compose_def},
        "nginx_upstream":   f"{svc_id}:{ext_port}" if needs_nginx and ext_port else None,
        "nginx_domain_var": f"{svc_id.upper().replace('-', '_')}_DOMAIN" if needs_nginx else None,
        "volumes":          data_volumes,
        "post_install_note": template_note if template_note else None,
    }

    templates_dir.mkdir(parents=True, exist_ok=True)
    out_path = templates_dir / f"{svc_id}.yaml"
    with open(out_path, "w") as f:
        yaml.dump(SERVICE, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"\n  ✔  Template saved to {out_path}")
    print(f"  To keep it: git add services/templates && git commit -m 'add {svc_id} template'\n")

    return SERVICE


def load_custom_templates(templates_dir: Path) -> list[dict]:
    """Load all .yaml templates from the templates directory."""
    if not templates_dir.exists():
        return []
    templates = []
    for f in sorted(templates_dir.glob("*.yaml")):
        with open(f) as fh:
            data = yaml.safe_load(fh)
            if data and "id" in data:
                templates.append(data)
    return templates
