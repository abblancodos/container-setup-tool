import questionary
import yaml
from pathlib import Path


def ask_custom_template(templates_dir: Path, builtins: list[dict] | None = None) -> dict | None:
    """Pick a builtin as base, use a saved template, or create from scratch."""
    saved = load_custom_templates(templates_dir)

    choices = []

    # Builtins that make sense to add more than once (APIs)
    repeatable = ["api-node", "api-rust"]
    for svc in (builtins or []):
        if svc["id"] in repeatable:
            label = f"{svc['name']}  [dim]— use as starting point[/dim]"
            choices.append(questionary.Choice(svc["name"] + "  — use as starting point",
                                              value=("builtin", svc)))

    for svc in saved:
        choices.append(questionary.Choice(svc["name"] + "  — saved template",
                                          value=("saved", svc)))

    choices.append(questionary.Choice("[+] Create new from scratch", value=("new", None)))
    choices.append(questionary.Choice("Cancel",                      value=("cancel", None)))

    result = questionary.select(
        "Add another service:",
        choices=choices,
    ).ask()

    if result is None:
        return None

    action, svc = result

    if action == "cancel":
        return None
    if action in ("builtin", "saved"):
        # Clone the service with new name/port to avoid ID conflicts
        return _customize_clone(svc)
    return _create_template(templates_dir)


def _customize_clone(base: dict) -> dict | None:
    """Ask for a new name/subdomain to clone an existing service."""
    import copy
    svc = copy.deepcopy(base)

    new_name = questionary.text(
        f"Service name for this instance (must be unique):",
        default=f"{base['id']}-2",
    ).ask()
    if not new_name:
        return None
    new_name = new_name.strip()

    new_subdomain = questionary.text(
        "Subdomain for nginx:",
        default=new_name,
    ).ask()
    if not new_subdomain:
        return None

    # Remap keys to avoid collision with the original
    prefix = new_name.upper().replace("-", "_")
    svc["id"] = new_name

    # Remap questions keys
    new_questions = []
    key_map = {}
    for q in svc.get("questions", []):
        new_key = f"{prefix}_{q['key'].split('_', 2)[-1]}" if "_" in q["key"] else f"{prefix}_{q['key']}"
        key_map[q["key"]] = new_key
        new_q = dict(q)
        new_q["key"] = new_key
        new_questions.append(new_q)

    # Update domain question default
    for q in new_questions:
        if "DOMAIN" in q["key"]:
            q["default"] = new_subdomain

    svc["questions"] = new_questions

    # Update nginx_domain_var
    if svc.get("nginx_domain_var"):
        old_domain_var = svc["nginx_domain_var"]
        svc["nginx_domain_var"] = key_map.get(old_domain_var, f"{prefix}_DOMAIN")

    # Update nginx_upstream with new service name
    if svc.get("nginx_upstream"):
        svc["nginx_upstream"] = f"{new_name}:3000"

    # Update compose key
    old_compose = svc.get("compose", {})
    svc["compose"] = {new_name: list(old_compose.values())[0]}

    return svc


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
