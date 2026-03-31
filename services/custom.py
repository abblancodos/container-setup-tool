import questionary
import yaml
from pathlib import Path


def ask_custom_template(templates_dir: Path) -> dict | None:
    """Create a brand new service template from scratch."""
    return _create_template(templates_dir)


def _create_template(templates_dir: Path) -> dict | None:
    """Walk the user through creating a new service template."""
    print()
    print("  A few questions to build the template.")
    print("  Leave fields blank if they don't apply.\n")

    svc_id = questionary.text(
        "Service ID (no spaces, e.g. myapp):",
        validate=lambda v: True if v.strip() else "Cannot be empty",
    ).ask()
    if svc_id is None:
        return None

    svc_name = questionary.text("Display name:").ask()
    svc_desc = questionary.text("Short description:").ask()
    image    = questionary.text(
        "Docker image (e.g. nginx:bookworm, myuser/myapp:latest):",
        validate=lambda v: True if v.strip() else "Required",
    ).ask()
    if image is None:
        return None

    ext_port = questionary.text(
        "Container port to expose (e.g. 3000), leave blank if none:",
    ).ask()

    needs_nginx = False
    if ext_port:
        needs_nginx = questionary.confirm(
            "Should nginx proxy to this service?", default=True
        ).ask()

    volumes_raw  = questionary.text(
        "Volumes to mount (comma-separated, e.g. ./data/myapp:/data):\n  blank = none:",
    ).ask()
    env_vars_raw = questionary.text(
        "Container environment variables (comma-separated, e.g. ENV=val):\n  blank = none:",
    ).ask()
    extra_q_raw  = questionary.text(
        "User-configurable variables (comma-separated keys, e.g. MY_SECRET,MY_PORT):\n  blank = none:",
    ).ask()
    depends_raw  = questionary.text(
        "Depends on another service? (e.g. postgres, blank = no):",
    ).ask()
    template_note = questionary.text(
        "Post-install note (blank = none):",
    ).ask()

    def split(s): return [x.strip() for x in s.split(",") if x.strip()] if s else []

    volumes_list  = split(volumes_raw)
    env_vars_list = split(env_vars_raw)
    depends_list  = split(depends_raw)
    extra_keys    = split(extra_q_raw)

    questions = []
    for key in extra_keys:
        default_val = questionary.text(f"  Default value for {key}:").ask() or ""
        label       = questionary.text(f"  Description for {key}:").ask() or key
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

    nginx_domain_var = None
    if needs_nginx and ext_port:
        domain_key = f"{svc_id.upper().replace('-', '_')}_DOMAIN"
        nginx_domain_var = domain_key
        subdomain = questionary.text(
            f"Default subdomain for nginx:", default=svc_id
        ).ask() or svc_id
        questions.append({"key": domain_key, "label": "Subdomain", "default": subdomain})

    data_volumes = [f"./data/{svc_id}"] if any("./data" in v for v in volumes_list) else []

    SERVICE = {
        "id":               svc_id,
        "name":             svc_name or svc_id,
        "description":      svc_desc or "",
        "questions":        questions,
        "compose":          {svc_id: compose_def},
        "nginx_upstream":   f"{svc_id}:{ext_port}" if needs_nginx and ext_port else None,
        "nginx_domain_var": nginx_domain_var,
        "volumes":          data_volumes,
        "post_install_note": template_note or None,
    }

    templates_dir.mkdir(parents=True, exist_ok=True)
    out_path = templates_dir / f"{svc_id}.yaml"
    with open(out_path, "w") as f:
        yaml.dump(SERVICE, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"\n  Saved to {out_path}")
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
