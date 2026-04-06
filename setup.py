#!/usr/bin/env python3
"""
Lab. Embebidos — Docker Server Setup Tool
Usage: python3 setup.py
"""

import os
import re
import sys
import importlib
import subprocess
from pathlib import Path

def _bootstrap_deps():
    """Install dependencies, handling Debian externally-managed environments."""
    here = Path(__file__).parent
    venv = here / ".venv"

    # Already inside a venv — just install
    if sys.prefix != sys.base_prefix:
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "-r", str(here / "requirements.txt"), "-q"])
        return

    # Try plain pip first (works on most systems)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "-r", str(here / "requirements.txt"), "-q"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return

    # Debian 12+ externally-managed — create .venv and re-exec inside it
    if "externally-managed-environment" in result.stderr:
        print("Detected externally-managed Python. Creating .venv ...")

        venv_result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            capture_output=True, text=True,
        )
        if venv_result.returncode != 0 and "ensurepip" in venv_result.stderr:
            print("python3-venv not found — installing via apt (needs sudo)...")
            subprocess.check_call(["sudo", "apt-get", "install", "-y", "python3-venv"])
            subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
        elif venv_result.returncode != 0:
            print(venv_result.stderr)
            sys.exit(1)

        subprocess.check_call([str(venv / "bin" / "pip"), "install",
                               "-r", str(here / "requirements.txt"), "-q"])
        os.execv(str(venv / "bin" / "python3"),
                 [str(venv / "bin" / "python3")] + sys.argv)
    else:
        print(result.stderr)
        sys.exit(1)


try:
    import questionary, yaml
    from rich.console import Console
    from rich.panel   import Panel
    from rich.table   import Table
    from rich         import box
except ImportError:
    print("Installing dependencies...")
    _bootstrap_deps()
    import questionary, yaml
    from rich.console import Console
    from rich.panel   import Panel
    from rich.table   import Table
    from rich         import box

from generators.compose import (
    generate_compose_layers, generate_env,
    generate_nginx_vhosts, create_data_dirs,
    ALWAYS_ON,
)
from generators.repos  import clone_service_repos, services_needing_clone
from services.custom   import ask_custom_template, load_custom_templates

console = Console()

BUILTIN_SERVICES = [
    "postgres",
    "gitea",
    "gitea_runner",
    "api_node",
    "api_rust",
    "svelte_app",
    "wikijs",
    "nginx",
]
BASE_DIR = Path(__file__).parent
TMPL_DIR = BASE_DIR / "services" / "templates"


# ─────────────────────────── helpers ────────────────────────────

def load_builtin(name: str) -> dict:
    mod = importlib.import_module(f"services.{name}")
    return mod.SERVICE


def detect_existing(output_dir: Path) -> list[str]:
    """Detect configured services by reading all docker-compose*.yml files.
    Resolves ${VAR} references using .env if present."""
    compose_files = sorted(output_dir.glob("docker-compose*.yml"))
    if not compose_files:
        return []

    # Load .env for variable resolution
    env_vars: dict = {}
    env_file = output_dir / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip()

    def resolve(name: str) -> str:
        return re.sub(
            r"\$\{([^}]+)\}",
            lambda m: env_vars.get(m.group(1), m.group(0)),
            name,
        )

    services = []
    for cf in compose_files:
        with open(cf) as f:
            data = yaml.safe_load(f) or {}
        for svc in (data.get("services") or {}):
            resolved = resolve(svc)
            if resolved not in services:
                services.append(resolved)
    return services


def needs_sudo(path: Path) -> bool:
    try:
        path.relative_to(Path.home())
        return False
    except ValueError:
        return True


def open_in_editor(path: Path):
    editor = os.environ.get("EDITOR", "nano")
    subprocess.call([editor, str(path)])


def header():
    console.print(Panel.fit(
        "[bold cyan]Lab. Embebidos — Docker Server Setup Tool[/bold cyan]",
        border_style="cyan",
    ))
    console.print()


def section(title: str):
    console.rule(f"[bold]{title}[/bold]")
    console.print()


# ─────────────────────────── step 1: directory ──────────────────

def _ask_directory(prompt: str, default: str) -> Path:
    """Pregunta por un directorio y advierte si requiere sudo."""
    console.print(
        "[dim]  ℹ  If the path is not writable by the current user, "
        "re-run the tool with sudo.[/dim]"
    )
    raw = questionary.text(prompt, default=default).ask()
    if raw is None:
        sys.exit(0)
    p = Path(raw).expanduser().resolve()
    if needs_sudo(p):
        console.print(
            f"[yellow]  ⚠  {p} is outside your home directory — "
            f"you may need to run: sudo python3 setup.py[/yellow]"
        )
        if not questionary.confirm("Continue anyway?", default=False).ask():
            sys.exit(0)
    p.mkdir(parents=True, exist_ok=True)
    return p


def step_directory() -> tuple[Path, Path]:
    section("1 · Install directory")

    output_dir = _ask_directory(
        "Where do you want to install the stack?",
        str(Path.cwd()),
    )
    console.print(f"[green]✔[/green]  Stack directory: [bold]{output_dir}[/bold]")

    data_dir = _ask_directory(
        "Where do you want to store persistent data?",
        str(output_dir / "data"),
    )
    console.print(f"[green]✔[/green]  Data directory:  [bold]{data_dir}[/bold]\n")

    return output_dir, data_dir


# ─────────────────────────── container manager ──────────────────

def _docker(args: list[str], output_dir: Path, capture=False):
    cmd = ["docker", "compose", "--project-directory", str(output_dir)] + args
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=output_dir)
    return subprocess.run(cmd, cwd=output_dir)


def _running_services(output_dir: Path) -> list[dict]:
    """Return list of {name, image, status} for all compose services."""
    r = _docker(["ps", "--format", "{{.Service}}|{{.Image}}|{{.Status}}"],
                output_dir, capture=True)
    services = []
    for line in r.stdout.splitlines():
        parts = line.split("|")
        if len(parts) == 3:
            services.append({"name": parts[0], "image": parts[1], "status": parts[2]})
    return services


def _all_services(output_dir: Path) -> list[str]:
    """Return all service names from compose files."""
    names = []
    env_vars: dict = {}
    env_file = output_dir / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip()

    def resolve(s):
        return re.sub(r"\$\{([^}]+)\}", lambda m: env_vars.get(m.group(1), m.group(0)), s)

    seen = set()
    for cf in sorted(output_dir.glob("docker-compose*.yml")):
        data = yaml.safe_load(cf.read_text()) or {}
        for svc in (data.get("services") or {}):
            resolved = resolve(svc)
            if resolved not in seen:
                seen.add(resolved)
                names.append(resolved)
    return names


def step_manage(output_dir: Path):
    section("Container manager")

    while True:
        running  = _running_services(output_dir)
        all_svcs = _all_services(output_dir)

        # Build status table
        status_map = {s["name"]: s for s in running}
        console.print("[dim]Services:[/dim]")
        for name in all_svcs:
            if name in status_map:
                st = status_map[name]["status"]
                img = status_map[name]["image"]
                color = "green" if "Up" in st else "yellow"
                console.print(f"  [{color}]●[/{color}]  {name:<25} [dim]{img}[/dim]  [dim]{st}[/dim]")
            else:
                console.print(f"  [dim]○  {name}[/dim]")
        console.print()

        action = questionary.select(
            "What do you want to do?",
            choices=[
                questionary.Choice("Start missing containers",   value="start"),
                questionary.Choice("Stop a container",           value="stop"),
                questionary.Choice("Restart a container",        value="restart"),
                questionary.Choice("View logs",                  value="logs"),
                questionary.Choice("Change image of a service",  value="image"),
                questionary.Separator(),
                questionary.Choice("Back",                       value="back"),
            ],
        ).ask()

        if action in ("back", None):
            break

        elif action == "start":
            not_running = [s for s in all_svcs if s not in status_map]
            if not not_running:
                console.print("[dim]All services are already running.[/dim]\n")
                continue
            to_start = questionary.checkbox(
                "Select services to start:",
                choices=[questionary.Choice(s, value=s) for s in not_running],
            ).ask() or []
            if to_start:
                _docker(["up", "-d"] + to_start, output_dir)
            console.print()

        elif action == "stop":
            if not running:
                console.print("[dim]No running containers.[/dim]\n")
                continue
            to_stop = questionary.checkbox(
                "Select services to stop:",
                choices=[questionary.Choice(s["name"], value=s["name"]) for s in running],
            ).ask() or []
            if to_stop:
                _docker(["stop"] + to_stop, output_dir)
            console.print()

        elif action == "restart":
            choices = [questionary.Choice(s["name"], value=s["name"]) for s in running]
            choices += [questionary.Choice(s, value=s) for s in all_svcs if s not in status_map]
            to_restart = questionary.checkbox("Select services to restart:", choices=choices).ask() or []
            if to_restart:
                _docker(["restart"] + to_restart, output_dir)
            console.print()

        elif action == "logs":
            choices = [questionary.Choice(s["name"], value=s["name"]) for s in running]
            if not choices:
                console.print("[dim]No running containers.[/dim]\n")
                continue
            svc = questionary.select("Which service?", choices=choices).ask()
            if svc:
                lines = questionary.text("How many lines?", default="50").ask() or "50"
                _docker(["logs", "--tail", lines, "-f", svc], output_dir)
            console.print()

        elif action == "image":
            choices = [questionary.Choice(
                f"{s}  [dim]{status_map[s]['image'] if s in status_map else 'not running'}[/dim]",
                value=s
            ) for s in all_svcs]
            svc = questionary.select("Which service?", choices=choices).ask()
            if not svc:
                continue

            # Find current image in compose file
            current_image = ""
            for cf in sorted(output_dir.glob("docker-compose*.yml")):
                data = yaml.safe_load(cf.read_text()) or {}
                for svc_name, svc_def in (data.get("services") or {}).items():
                    if svc_name == svc and svc_def.get("image"):
                        current_image = svc_def["image"]
                        current_file  = cf
                        break

            new_image = questionary.text(
                f"New image for {svc}:",
                default=current_image,
            ).ask()

            if new_image and new_image != current_image:
                # Update the compose file
                cf_content = current_file.read_text()
                cf_content = cf_content.replace(
                    f"image: {current_image}",
                    f"image: {new_image}",
                )
                current_file.write_text(cf_content)
                console.print(f"[green]✔[/green]  Updated {current_file.name}")

                pull = questionary.confirm("Pull new image now?", default=True).ask()
                if pull:
                    _docker(["pull", new_image.split(":")[0]], output_dir)

                restart = questionary.confirm(f"Restart {svc} with new image?", default=True).ask()
                if restart:
                    _docker(["up", "-d", "--force-recreate", svc], output_dir)
            console.print()


# ─────────────────────────── template picker ────────────────────

def pick_or_create_service(all_svcs: list[dict], templates_dir: Path) -> dict | None:
    """
    Select menu shown when user picks [+] Add another service.
    Lists all builtin + saved templates, then offers Create new at the bottom.
    Selected template is cloned with a fresh unique ID so multiple instances work.
    """
    choices = []
    for svc in all_svcs:
        label = f"{svc['name']}  — {svc['description']}"
        choices.append(questionary.Choice(label, value=svc))
    choices.append(questionary.Separator("─────────────────────"))
    choices.append(questionary.Choice("[+] Create new template...", value="__new__"))
    choices.append(questionary.Choice("Cancel", value=None))

    picked = questionary.select(
        "Which service do you want to add?",
        choices=choices,
        use_shortcuts=False,
    ).ask()

    if picked is None:
        return None

    if picked == "__new__":
        from services.custom import ask_custom_template
        return ask_custom_template(templates_dir)

    # Clone the template so it gets a unique ID (allows multiple instances)
    import copy
    svc = copy.deepcopy(picked)
    new_id = questionary.text(
        f"Instance name for this {svc['name']} (used as service ID, no spaces):",
        default=svc["id"],
        validate=lambda v: True if v.strip() else "Cannot be empty",
    ).ask()
    if new_id is None:
        return None

    new_id = new_id.strip()
    if new_id == svc["id"]:
        return svc  # same id, no renaming needed

    old_id  = svc["id"]
    old_key = old_id.upper().replace("-", "_")
    new_key = new_id.upper().replace("-", "_")

    # Rename values (env vars, image names, upstream) but NOT compose service keys
    # Compose service keys must be static strings — variables not allowed there
    def rename_val(v):
        if isinstance(v, str):
            return v.replace(old_id, new_id).replace(old_key, new_key)
        if isinstance(v, list):
            return [rename_val(i) for i in v]
        if isinstance(v, dict):
            return {k: rename_val(val) for k, val in v.items()}
        return v

    # Rebuild compose with new static key derived from new_id
    new_compose = {}
    for old_svc_key, svc_def in svc["compose"].items():
        new_svc_key = new_id  # use new_id as the static compose service name
        new_compose[new_svc_key] = rename_val(svc_def)

    svc = rename_val(svc)
    svc["id"]      = new_id
    svc["compose"] = new_compose

    # Fix nginx_upstream to point to new static service name
    if svc.get("nginx_upstream"):
        # replace the old service key in upstream (e.g. "api-rust:3000" -> "sensor-api:3000")
        svc["nginx_upstream"] = f"{new_id}:{svc['nginx_upstream'].split(':')[-1]}"

    return svc


# ─────────────────────────── step 2: services ───────────────────────

def step_services(output_dir: Path) -> list[dict]:
    section("2 · Services")

    existing = detect_existing(output_dir)
    builtin  = [load_builtin(s) for s in BUILTIN_SERVICES]
    custom   = load_custom_templates(TMPL_DIR)
    all_svcs = builtin + custom

    if existing:
        console.print("[cyan]ℹ  Found an existing stack in that directory:[/cyan]")
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        for name in existing:
            table.add_row("[dim]•[/dim]", name)
        console.print(table)
        console.print()

        action = questionary.select(
            "What do you want to do?",
            choices=[
                questionary.Choice("Modify existing stack (add / remove services)", value="modify"),
                questionary.Choice("Manage containers (start / stop / restart / logs / image)", value="manage"),
                questionary.Choice("Bootstrap services (initial wizard setup)", value="bootstrap"),
                questionary.Choice("Update domains (change BASE_DOMAIN + nginx server_names)", value="domains"),
                questionary.Choice("Generate a new stack from scratch (overwrites)",  value="new"),
                questionary.Choice("Exit", value="exit"),
            ],
        ).ask()

        if action in ("exit", None):
            sys.exit(0)

        if action == "manage":
            step_manage(output_dir)
            sys.exit(0)

        if action == "bootstrap":
            builtin  = [load_builtin(s) for s in BUILTIN_SERVICES]
            custom   = load_custom_templates(TMPL_DIR)
            all_svcs = builtin + custom
            existing_svcs = [s for s in all_svcs if s["id"] in existing]
            step_bootstrap(output_dir, existing_svcs)
            sys.exit(0)

        if action == "domains":
            step_update_domains(output_dir)
            sys.exit(0)
    else:
        console.print("[dim]No existing stack found. Starting from scratch.[/dim]\n")
        action = "new"

    choices = []
    for svc in all_svcs:
        label = f"{svc['name']}  [dim]— {svc['description']}[/dim]"
        pre   = svc["id"] in existing if action == "modify" else False
        choices.append(questionary.Choice(label, value=svc["id"], checked=pre))
    choices.append(questionary.Choice("[+] Add another service...", value="__custom__"))

    selected_ids = questionary.checkbox("Select the services to include:", choices=choices).ask()
    if selected_ids is None:
        sys.exit(0)

    selected_services = []
    for sid in selected_ids:
        if sid == "__custom__":
            new_svc = pick_or_create_service(all_svcs, TMPL_DIR)
            if new_svc:
                selected_services.append(new_svc)
        else:
            match = next((s for s in all_svcs if s["id"] == sid), None)
            if match:
                selected_services.append(match)

    if not selected_services:
        console.print("[yellow]No services selected. Exiting.[/yellow]")
        sys.exit(0)

    console.print()
    return selected_services


# ─────────────────────────── step 3: configuration ──────────────

def step_configure(selected_services: list[dict], output_dir: Path) -> dict:
    section("3 · Configuration")

    mode = questionary.select(
        "How do you want to configure the services?",
        choices=[
            questionary.Choice(
                "Guided  — answer each field one by one (recommended for first-time setup)",
                value="guided",
            ),
            questionary.Choice(
                "Editor  — open .env with defaults directly in your editor (faster for experienced users)",
                value="editor",
            ),
        ],
    ).ask()

    if mode is None:
        sys.exit(0)

    if mode == "guided":
        return _guided(selected_services)
    else:
        return _editor(selected_services, output_dir)


def _guided(selected_services: list[dict]) -> dict:
    """Walk through each field one by one, grouped by service."""
    console.print("[dim]Press Enter to accept the default value.[/dim]\n")
    answers: dict = {}

    for svc in selected_services:
        if not svc.get("questions"):
            continue
        console.print(f"[bold cyan]{svc['name']}[/bold cyan]")
        for q in svc["questions"]:
            val = questionary.text(
                f"  {q['label']}:",
                default=str(q.get("default", "")),
            ).ask()
            if val is None:
                sys.exit(0)
            answers[q["key"]] = val
        console.print()

    return answers


def _editor(selected_services: list[dict], output_dir: Path) -> dict:
    """Write .env with defaults, open it in $EDITOR, read back the result."""
    env_path = output_dir / ".env"

    lines = [
        "# infra-setup — edit the values below, save and close to continue",
        "# Lines starting with # are comments and are ignored",
        "",
    ]
    for svc in selected_services:
        if not svc.get("questions"):
            continue
        lines.append(f"# ── {svc['name']} ──")
        for q in svc["questions"]:
            lines.append(f"# {q['label']}")
            lines.append(f"{q['key']}={q.get('default', '')}")
        lines.append("")

    env_path.write_text("\n".join(lines))
    console.print(f"[dim]Opening {env_path} in your editor...[/dim]\n")
    open_in_editor(env_path)

    # Parse the edited file back into a dict
    answers: dict = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            answers[key.strip()] = val.strip()

    console.print(f"[green]✔[/green]  Read {len(answers)} value(s) from .env\n")
    return answers


# ─────────────────────────── step 3b: clone repos ───────────────

def step_clone_repos(selected_services: list[dict], answers: dict, output_dir: Path):
    needs_clone = services_needing_clone(selected_services)
    if not needs_clone:
        return

    section("3b · Service repos")

    # Detect if this looks like a first-time run (Gitea itself is in the stack)
    gitea_in_stack = any(s["id"] == "gitea" for s in selected_services)
    gitea_base     = answers.get("GITEA_BASE", "").strip()

    if gitea_in_stack and not gitea_base:
        console.print(
            "[cyan]ℹ  Gitea is part of this stack, so it may not be running yet.[/cyan]\n"
            "   You can skip cloning now — the compose files will be generated anyway.\n"
            "   Once Gitea is up and you've pushed the repos, run setup.py again\n"
            "   and it will clone them automatically.\n"
        )
        skip = questionary.select(
            "What do you want to do?",
            choices=[
                questionary.Choice("Skip cloning for now — generate files only", value="skip"),
                questionary.Choice("Gitea is already running — clone now",        value="clone"),
            ],
        ).ask()
        if skip is None or skip == "skip":
            answers["GITEA_BASE"] = ""
            console.print("[dim]Skipped. Run setup.py again after Gitea is up to clone repos.[/dim]\n")
            return

    # Ask for Gitea base URL if not already known
    if not gitea_base:
        default_url = (
            f"http://{answers.get('GITEA_DOMAIN', 'git')}.{answers.get('BASE_DOMAIN', 'localhost')}"
        )
        gitea_base = questionary.text(
            "Gitea server base URL (e.g. http://git.myserver.com):",
            default=default_url,
        ).ask()
        if gitea_base is None:
            sys.exit(0)
        answers["GITEA_BASE"] = gitea_base.rstrip("/")

    console.print(f"[dim]Cloning from {answers['GITEA_BASE']} → {output_dir}/services/[/dim]\n")

    results = clone_service_repos(selected_services, answers["GITEA_BASE"], output_dir)
    failed  = []

    for r in results:
        if r["status"] == "cloned":
            console.print(f"[green]✔[/green]  {r['service']}  cloned")
        elif r["status"] == "pulled":
            console.print(f"[green]✔[/green]  {r['service']}  up to date (pulled)")
        elif r["status"] == "skipped":
            console.print(f"[yellow]⚠[/yellow]  {r['service']}  {r['detail']}")
        else:
            console.print(f"[red]✗[/red]  {r['service']}  [red]{r['detail']}[/red]")
            failed.append(r["service"])

    if failed:
        console.print()
        console.print(
            f"[yellow]⚠  {len(failed)} repo(s) could not be cloned: {', '.join(failed)}[/yellow]\n"
            "   The compose files will still be generated.\n"
            "   Push the repos to Gitea and run setup.py again to finish.\n"
        )
        # Don't ask — just continue. The stack is usable without them (can't build yet, but that's fine).

    console.print()


# ─────────────────────────── step 4: generate ───────────────────

def step_generate(selected_services: list[dict], answers: dict, output_dir: Path, data_dir: Path) -> list[Path]:
    section("4 · Generating files")

    always   = [s for s in selected_services if s["id"] in ALWAYS_ON]
    optional = [s for s in selected_services if s["id"] not in ALWAYS_ON]

    base_path, override_paths = generate_compose_layers(always, optional, output_dir, data_dir)
    console.print(f"[green]✔[/green]  {base_path.name}  [dim](base: network + always-on services)[/dim]")
    for p in override_paths:
        console.print(f"[green]✔[/green]  {p.name}")

    generate_env(selected_services, answers, output_dir, override_paths)
    console.print(f"[green]✔[/green]  .env  [dim](COMPOSE_FILE + variables, added to .gitignore)[/dim]")

    if any(s["id"] == "nginx" for s in selected_services):
        vhosts = generate_nginx_vhosts(selected_services, answers, output_dir)
        for domain, path in vhosts:
            console.print(f"[green]✔[/green]  nginx/conf.d/{path.name}  [dim]→ {domain}[/dim]")

    dirs = create_data_dirs(selected_services, data_dir)
    console.print(f"[green]✔[/green]  {len(dirs)} data director{'y' if len(dirs)==1 else 'ies'} created\n")

    # Post-install hooks (e.g. chown for rootless containers)
    run_post_hooks(selected_services, data_dir)

    return override_paths


# ─────────────────────────── post hooks ────────────────────────

def run_post_hooks(selected_services: list[dict], data_dir: Path):
    for svc in selected_services:
        hook = svc.get("post_create_hook")
        if not hook:
            continue
        for cmd in hook(data_dir):
            console.print(f"[dim]  $ {' '.join(cmd)}[/dim]")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                console.print(f"[yellow]  ⚠  Hook failed: {result.stderr.strip()}[/yellow]")
            else:
                console.print(f"[green]  ✔[/green]  {cmd[-1]}")


# ─────────────────────────── step 5: launch ────────────────────

def step_launch(output_dir: Path):
    section("5 · Starting containers")

    result = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print("[yellow]⚠  Could not query Docker — skipping auto-launch.[/yellow]")
        console.print("[dim]Run: docker compose up -d manually.[/dim]")
        return

    available_images = set(result.stdout.splitlines())

    env_vars: dict = {}
    env_file = output_dir / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip()

    def resolve(s: str) -> str:
        return re.sub(r"\$\{([^}]+)\}", lambda m: env_vars.get(m.group(1), m.group(0)), s)

    launchable = []
    skipped    = []
    seen: set  = set()

    for cf in sorted(output_dir.glob("docker-compose*.yml")):
        data = yaml.safe_load(cf.read_text()) or {}
        for svc_name, svc_def in (data.get("services") or {}).items():
            if svc_name in seen:
                continue
            seen.add(svc_name)
            image = resolve(svc_def.get("image", ""))
            if not image or image.startswith("$"):
                skipped.append(svc_name)
                continue
            if ":" not in image:
                image += ":latest"
            repo = image.split(":")[0]
            if image in available_images or any(i.startswith(repo + ":") for i in available_images):
                launchable.append(svc_name)
            else:
                skipped.append(svc_name)

    if not launchable:
        console.print("[yellow]No images available locally yet — nothing to start.[/yellow]")
        console.print("[dim]Pull images first: docker compose pull[/dim]")
        return

    console.print(f"[dim]Images ready for {len(launchable)} service(s):[/dim]")
    for s in launchable:
        console.print(f"  [green]✔[/green]  {s}")
    if skipped:
        console.print(f"\n[dim]Skipping {len(skipped)} — image not built yet:[/dim]")
        for s in skipped:
            console.print(f"  [dim]○  {s}[/dim]")

    console.print()
    ok = questionary.confirm(
        f"Start {len(launchable)} available container(s) now?", default=True
    ).ask()
    if not ok:
        console.print("[dim]Skipped. Run: docker compose up -d when ready.[/dim]")
        return

    cmd = ["docker", "compose", "--project-directory", str(output_dir),
           "up", "-d"] + launchable
    console.print()
    result = subprocess.run(cmd, cwd=output_dir)
    if result.returncode == 0:
        console.print(f"\n[green]✔[/green]  {len(launchable)} container(s) started.\n")
    else:
        console.print("\n[red]✗  docker compose reported errors — check output above.[/red]\n")
# ─────────────────────────── step_update_domains ───────────────

def step_update_domains(output_dir: Path):
    section("Update domains")

    # Leer .env actual
    env_file = output_dir / ".env"
    if not env_file.exists():
        console.print("[red]✗  No .env found in stack directory.[/red]")
        return

    env_vars: dict = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env_vars[k.strip()] = v.strip()

    current_domain = env_vars.get("BASE_DOMAIN", "localhost")
    console.print(f"[dim]Current BASE_DOMAIN: {current_domain}[/dim]\n")

    new_domain = questionary.text(
        "New base domain (e.g. nm.35-208-114-233.nip.io or mylab.com):",
        default=current_domain,
    ).ask()
    if not new_domain or new_domain == current_domain:
        console.print("[dim]No change.[/dim]")
        return

    nginx_conf_dir = output_dir / "nginx" / "conf.d"
    if not nginx_conf_dir.exists():
        console.print("[yellow]⚠  No nginx/conf.d directory found.[/yellow]")
        return

    # Cargar todos los servicios para obtener nginx_domain_var
    builtin  = [load_builtin(s) for s in BUILTIN_SERVICES]
    custom   = load_custom_templates(TMPL_DIR)
    all_svcs = builtin + custom

    updated = []
    for svc in all_svcs:
        domain_var = svc.get("nginx_domain_var")
        if not domain_var:
            continue
        conf_path = nginx_conf_dir / f"{svc['id']}.conf"
        if not conf_path.exists():
            continue
        subdomain = env_vars.get(domain_var, svc["id"])
        new_server_name = f"{subdomain}.{new_domain}"

        content = conf_path.read_text()
        # Reemplaza cualquier server_name existente
        import re
        content = re.sub(
            r"server_name\s+[^;]+;",
            f"server_name {new_server_name};",
            content,
        )
        conf_path.write_text(content)
        updated.append((svc["name"], new_server_name))
        console.print(f"[green]✔[/green]  {svc['name']} → {new_server_name}")

    if not updated:
        console.print("[yellow]No nginx confs found to update.[/yellow]")
        return

    # Actualizar BASE_DOMAIN en .env
    env_content = env_file.read_text()
    env_content = re.sub(r"BASE_DOMAIN=.*", f"BASE_DOMAIN={new_domain}", env_content)
    env_file.write_text(env_content)
    console.print(f"[green]✔[/green]  .env BASE_DOMAIN updated to {new_domain}")

    # Reiniciar nginx
    console.print("\n[dim]Restarting nginx...[/dim]")
    result = subprocess.run(
        ["docker", "compose", "--project-directory", str(output_dir), "restart", "nginx"],
        capture_output=True, text=True, cwd=output_dir,
    )
    if result.returncode == 0:
        console.print("[green]✔[/green]  nginx restarted\n")
    else:
        console.print(f"[yellow]⚠  nginx restart failed: {result.stderr.strip()}[/yellow]")
        console.print("[dim]Run: docker restart server-lab-nginx-1 manually[/dim]\n")

    console.print("[bold]Done.[/bold] Update your reverse proxy (Caddy/Cloudflare) to point to this server.\n")


# ─────────────────────────── step_bootstrap ────────────────────

BOOTSTRAP_STATE_FILE = ".bootstrap-state.json"


def _load_bootstrap_state(output_dir: Path) -> dict:
    state_file = output_dir / BOOTSTRAP_STATE_FILE
    if state_file.exists():
        import json
        return json.loads(state_file.read_text())
    return {}


def _save_bootstrap_state(output_dir: Path, state: dict):
    import json
    state_file = output_dir / BOOTSTRAP_STATE_FILE
    state_file.write_text(json.dumps(state, indent=2))


def _is_bootstrap_done(svc: dict, state: dict) -> bool:
    """Check via saved state or by running the service's check_cmd."""
    svc_id = svc["id"]
    if state.get(svc_id) == "done":
        return True
    check_cmd = svc.get("bootstrap", {}).get("check_cmd")
    if check_cmd:
        result = subprocess.run(check_cmd, capture_output=True)
        return result.returncode == 0
    return False


def _get_server_ip() -> str:
    """Obtiene la IP local del servidor via hostname -I."""
    result = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip().split()[0]
    return "<server-ip>"


def _clear_all_default_servers(nginx_conf_dir: Path):
    """Quita default_server de todos los confs para evitar duplicados."""
    if not nginx_conf_dir.exists():
        return
    for conf in nginx_conf_dir.glob("*.conf"):
        content = conf.read_text()
        if "default_server" in content:
            conf.write_text(content.replace("listen 80 default_server;", "listen 80;"))


def _set_default_server(nginx_conf_dir: Path, upstream_conf: str, enable: bool):
    """Add or remove default_server from a given nginx conf file."""
    conf_path = nginx_conf_dir / upstream_conf
    if not conf_path.exists():
        return
    _clear_all_default_servers(nginx_conf_dir)
    if enable:
        content = conf_path.read_text()
        content = content.replace("listen 80;", "listen 80 default_server;", 1)
        conf_path.write_text(content)


def step_bootstrap(output_dir: Path, selected_services: list[dict]):
    bootstrap_svcs = [s for s in selected_services if s.get("bootstrap")]
    if not bootstrap_svcs:
        return

    section("Bootstrap — Initial wizard setup")

    state = _load_bootstrap_state(output_dir)
    nginx_conf_dir = output_dir / "nginx" / "conf.d"
    server_ip = _get_server_ip()

    # Show status table
    console.print("[dim]Services requiring initial setup:[/dim]")
    for svc in bootstrap_svcs:
        done = _is_bootstrap_done(svc, state)
        mark = "[green]✔  done[/green]" if done else "[yellow]○  pending[/yellow]"
        console.print(f"  {mark}  {svc['name']}")
    console.print()

    pending = [s for s in bootstrap_svcs if not _is_bootstrap_done(s, state)]
    if not pending:
        console.print("[green]All services already bootstrapped.[/green]\n")
        return

    ok = questionary.confirm(
        f"Run bootstrap wizard for {len(pending)} pending service(s)?",
        default=True,
    ).ask()
    if not ok:
        console.print("[dim]Skipped. Run setup.py again when ready.[/dim]\n")
        return

    for svc in pending:
        bootstrap = svc["bootstrap"]
        note = bootstrap["note"].replace("{server_ip}", server_ip)

        console.print(f"\n[bold cyan]── {svc['name']} ──[/bold cyan]")
        console.print(f"[dim]{note}[/dim]\n")

        # Find this service's nginx conf and set it as default_server
        nginx_conf = f"{svc['id']}.conf"
        has_nginx = (nginx_conf_dir / nginx_conf).exists()
        if has_nginx:
            _set_default_server(nginx_conf_dir, nginx_conf, enable=True)
            subprocess.run(["docker", "restart", "server-lab-nginx-1"],
                           capture_output=True)
            console.print(f"[green]✔[/green]  nginx default_server set — open [bold]http://{server_ip}[/bold] in your browser")

        questionary.text(
            f"Press Enter when you have finished the {svc['name']} wizard (or type 'skip' to skip):",
            default="",
        ).ask()

        if has_nginx:
            _set_default_server(nginx_conf_dir, nginx_conf, enable=False)
            subprocess.run(["docker", "restart", "server-lab-nginx-1"],
                           capture_output=True)
            console.print("[green]✔[/green]  nginx default_server reverted")

        mark = questionary.confirm(
            f"Mark {svc['name']} as bootstrapped?", default=True
        ).ask()
        if mark:
            state[svc["id"]] = "done"
            _save_bootstrap_state(output_dir, state)
            console.print(f"[green]✔[/green]  {svc['name']} marked as done\n")

    console.print("[green]Bootstrap complete.[/green]\n")


# ─────────────────────────── step 6: summary ────────────────────

def step_summary(selected_services: list[dict], override_paths: list[Path], output_dir: Path, answers: dict):
    section("6 · Done")

    console.print(f"[bold]Stack generated at:[/bold] {output_dir}\n")

    # First-time bootstrap order if Gitea is in the stack
    gitea_in_stack   = any(s["id"] == "gitea" for s in selected_services)
    repos_pending    = bool(services_needing_clone(selected_services)) and not answers.get("GITEA_BASE")

    if gitea_in_stack and repos_pending:
        console.print("[bold]Bootstrap order (first-time setup):[/bold]")
        console.print(f"  1.  [bold cyan]cd {output_dir}[/bold cyan]")
        console.print( "  2.  [bold cyan]docker compose up -d[/bold cyan]  — starts Gitea, nginx, postgres")
        console.print( "  3.  Open Gitea and finish the install wizard")
        console.print( "  4.  Push your service repos (dbsync-engine, etc.) to Gitea")
        console.print( "  5.  [bold cyan]python3 setup.py[/bold cyan]  — run again to clone the repos and rebuild\n")
    else:
        console.print("To start the stack:")
        console.print(f"  [bold cyan]cd {output_dir}[/bold cyan]")
        console.print(f"  [bold cyan]docker compose up -d[/bold cyan]\n")

    console.print("[bold]To add or remove a service later:[/bold]")
    console.print("  Edit [cyan]COMPOSE_FILE[/cyan] in [cyan].env[/cyan] — add or remove a filename from the list")
    console.print("  Then: [bold cyan]docker compose up -d[/bold cyan]  "
                  "[dim](already-running services are not restarted)[/dim]\n")

    console.print("[bold]To bulk-edit all variables:[/bold]")
    console.print(f"  [bold cyan]$EDITOR {output_dir}/.env[/bold cyan]\n")

    all_overrides = sorted(output_dir.glob("docker-compose.*.yml"))
    if all_overrides:
        console.print("[dim]Available service files:[/dim]")
        for p in all_overrides:
            active = p in override_paths
            mark   = "[green]active  [/green]" if active else "[dim]inactive[/dim]"
            console.print(f"  {mark}  {p.name}")
        console.print()

    notes = [(s["name"], s["post_install_note"])
             for s in selected_services if s.get("post_install_note")]
    if notes:
        console.print("[bold]Post-install notes:[/bold]")
        for name, note in notes:
            console.print(f"\n[cyan]{name}[/cyan]")
            for line in note.splitlines():
                console.print(f"  {line}")
        console.print()


# ─────────────────────────── main ───────────────────────────────

def main():
    header()

    output_dir, data_dir = step_directory()
    selected_services    = step_services(output_dir)
    answers              = step_configure(selected_services, output_dir)

    console.print()
    if not questionary.confirm("Everything looks good? Generate the files.", default=True).ask():
        console.print("[dim]Cancelled.[/dim]")
        sys.exit(0)

    step_clone_repos(selected_services, answers, output_dir)
    override_paths = step_generate(selected_services, answers, output_dir, data_dir)
    step_launch(output_dir)
    step_bootstrap(output_dir, selected_services)
    step_summary(selected_services, override_paths, output_dir, answers)


if __name__ == "__main__":
    main()
