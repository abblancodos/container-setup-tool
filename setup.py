#!/usr/bin/env python3
"""
Lab. Embebidos — Docker Server Setup Tool
Usage: python3 setup.py
"""

import os
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
    """Detect configured services by reading all docker-compose*.yml files."""
    compose_files = sorted(output_dir.glob("docker-compose*.yml"))
    if not compose_files:
        return []
    services = []
    for cf in compose_files:
        with open(cf) as f:
            data = yaml.safe_load(f) or {}
        for svc in (data.get("services") or {}):
            if svc not in services:
                services.append(svc)
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

def step_directory() -> Path:
    section("1 · Install directory")

    raw = questionary.text(
        "Where do you want to install the stack?",
        default=str(Path.cwd()),
    ).ask()

    if raw is None:
        sys.exit(0)

    output_dir = Path(raw).expanduser().resolve()

    if needs_sudo(output_dir):
        console.print(
            f"[yellow]⚠  {output_dir} is outside your home directory — "
            f"you may need sudo to write files there.[/yellow]"
        )
        if not questionary.confirm("Continue anyway?", default=False).ask():
            sys.exit(0)

    output_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✔[/green]  Directory: [bold]{output_dir}[/bold]\n")
    return output_dir


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

    # Rename all keys and compose service names that reference the old id
    old_id  = svc["id"]
    old_key = old_id.upper().replace("-", "_")
    new_key = new_id.upper().replace("-", "_")

    def rename(v):
        if isinstance(v, str):
            return v.replace(old_id, new_id).replace(old_key, new_key)
        if isinstance(v, list):
            return [rename(i) for i in v]
        if isinstance(v, dict):
            return {rename(k): rename(val) for k, val in v.items()}
        return v

    svc = rename(svc)
    svc["id"] = new_id
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
                questionary.Choice("Generate a new stack from scratch (overwrites)",  value="new"),
                questionary.Choice("Exit", value="exit"),
            ],
        ).ask()

        if action in ("exit", None):
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

def step_generate(selected_services: list[dict], answers: dict, output_dir: Path) -> list[Path]:
    section("4 · Generating files")

    always   = [s for s in selected_services if s["id"] in ALWAYS_ON]
    optional = [s for s in selected_services if s["id"] not in ALWAYS_ON]

    base_path, override_paths = generate_compose_layers(always, optional, output_dir)
    console.print(f"[green]✔[/green]  {base_path.name}  [dim](base: network + always-on services)[/dim]")
    for p in override_paths:
        console.print(f"[green]✔[/green]  {p.name}")

    generate_env(selected_services, answers, output_dir, override_paths)
    console.print(f"[green]✔[/green]  .env  [dim](COMPOSE_FILE + variables, added to .gitignore)[/dim]")

    if any(s["id"] == "nginx" for s in selected_services):
        vhosts = generate_nginx_vhosts(selected_services, answers, output_dir)
        for domain, path in vhosts:
            console.print(f"[green]✔[/green]  nginx/conf.d/{path.name}  [dim]→ {domain}[/dim]")

    dirs = create_data_dirs(selected_services, output_dir)
    console.print(f"[green]✔[/green]  {len(dirs)} data director{'y' if len(dirs)==1 else 'ies'} created\n")

    return override_paths


# ─────────────────────────── step 5: summary ────────────────────

def step_summary(selected_services: list[dict], override_paths: list[Path], output_dir: Path, answers: dict):
    section("5 · Done")

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

    output_dir        = step_directory()
    selected_services = step_services(output_dir)
    answers           = step_configure(selected_services, output_dir)

    console.print()
    if not questionary.confirm("Everything looks good? Generate the files.", default=True).ask():
        console.print("[dim]Cancelled.[/dim]")
        sys.exit(0)

    step_clone_repos(selected_services, answers, output_dir)
    override_paths = step_generate(selected_services, answers, output_dir)
    step_summary(selected_services, override_paths, output_dir, answers)


if __name__ == "__main__":
    main()
