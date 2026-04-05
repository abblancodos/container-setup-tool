"""
generators/compose.py

Genera un archivo docker-compose por capa:
  docker-compose.yml              ← base: red infra + servicios "always on"
  docker-compose.<id>.yml         ← uno por servicio opcional
  .env                            ← variables + COMPOSE_FILE con los activos
  nginx/conf.d/<id>.conf          ← un vhost por servicio con nginx_upstream
"""

import yaml
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ALWAYS_ON = {"nginx"}   # servicios que van en el base, no en su propio override


def _dump(data: dict, path: Path):
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _resolve_volumes(definition: dict, data_dir: Path) -> dict:
    """Rewrite ./data/<rel> volume paths to use the configured data_dir."""
    defn = dict(definition)
    if "volumes" in defn:
        new_vols = []
        for vol in defn["volumes"]:
            if isinstance(vol, str) and vol.startswith("./data/"):
                parts = vol.split(":", 1)
                rel = parts[0][len("./data/"):]
                host_path = str(data_dir / rel)
                new_vols.append(f"{host_path}:{parts[1]}" if len(parts) == 2 else host_path)
            else:
                new_vols.append(vol)
        defn["volumes"] = new_vols
    return defn


def _service_block(svc: dict, output_dir: Path, data_dir: Path) -> dict:
    """Construye el bloque services: para un servicio, añadiendo la red infra."""
    block = {}
    for name, definition in svc["compose"].items():
        defn = _resolve_volumes(dict(definition), data_dir)
        defn.setdefault("networks", ["infra"])
        block[name] = defn
    return block


# ── archivos compose ─────────────────────────────────────────────

def generate_compose_layers(
    always_services: list[dict],
    optional_services: list[dict],
    output_dir: Path,
    data_dir: Path,
) -> tuple[Path, list[Path]]:
    """
    Genera:
      - docker-compose.yml  (base con la red y los servicios always-on)
      - docker-compose.<id>.yml  (uno por servicio opcional)

    Devuelve (base_path, [override_paths...])
    """
    # Base: solo la red + servicios always-on
    base: dict = {
        "networks": {"infra": {"driver": "bridge"}},
        "services": {},
    }
    for svc in always_services:
        base["services"].update(_service_block(svc, output_dir, data_dir))

    base_path = output_dir / "docker-compose.yml"
    _dump(base, base_path)

    # Un override por servicio opcional
    override_paths = []
    for svc in optional_services:
        override = {
            "services": _service_block(svc, output_dir, data_dir),
            "networks": {"infra": {}},   # referencia a la red del base
        }
        path = output_dir / f"docker-compose.{svc['id']}.yml"
        _dump(override, path)
        override_paths.append(path)

    return base_path, override_paths


# ── .env ─────────────────────────────────────────────────────────

def generate_env(
    selected_services: list[dict],
    answers: dict,
    output_dir: Path,
    active_overrides: list[Path],
) -> Path:
    """
    Genera .env con:
      - COMPOSE_FILE con todos los archivos activos separados por :
      - Variables de cada servicio agrupadas por sección
    """
    # COMPOSE_FILE — base + overrides activos
    all_files = [output_dir / "docker-compose.yml"] + active_overrides
    compose_file_val = ":".join(str(p.relative_to(output_dir)) for p in all_files)

    lines = [
        "# infra-setup — do not commit this file",
        "# To add/remove a service, edit COMPOSE_FILE and run: docker compose up -d",
        "",
        f"# Active compose files (edit this line to add or remove a service)",
        f"COMPOSE_FILE={compose_file_val}",
        "",
        "# Gitea server base URL (used for cloning service repos)",
        "GITEA_BASE=",
        "",
    ]

    for svc in selected_services:
        if not svc.get("questions"):
            continue
        lines.append(f"# --- {svc['name']} ---")
        for q in svc["questions"]:
            key = q["key"]
            val = answers.get(key, q.get("default", ""))
            lines.append(f"{key}={val}")
        lines.append("")

    env_path = output_dir / ".env"
    with open(env_path, "w") as f:
        f.write("\n".join(lines))

    # .gitignore
    gitignore = output_dir / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    additions = []
    for entry in [".env", "data/", ".venv/", "__pycache__/"]:
        if entry not in existing:
            additions.append(entry)
    if additions:
        with open(gitignore, "a") as f:
            f.write("\n" + "\n".join(additions) + "\n")

    return env_path


# ── nginx vhosts ─────────────────────────────────────────────────

def generate_nginx_vhosts(
    selected_services: list[dict],
    answers: dict,
    output_dir: Path,
) -> list[tuple[str, Path]]:
    nginx_dir = output_dir / "nginx" / "conf.d"
    nginx_dir.mkdir(parents=True, exist_ok=True)

    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    tpl = env.get_template("nginx-vhost.conf.j2")

    base_domain = answers.get("BASE_DOMAIN", "localhost")
    generated = []

    for svc in selected_services:
        upstream  = svc.get("nginx_upstream")
        domain_var = svc.get("nginx_domain_var")
        if not upstream or not domain_var:
            continue
        subdomain = answers.get(domain_var, svc["id"])
        domain = f"{subdomain}.{base_domain}" if base_domain != "localhost" else subdomain
        content = tpl.render(domain=domain, upstream=upstream)
        vhost_path = nginx_dir / f"{svc['id']}.conf"
        vhost_path.write_text(content)
        generated.append((domain, vhost_path))

    return generated


# ── directorios de datos ─────────────────────────────────────────

def create_data_dirs(selected_services: list[dict], data_dir: Path) -> list[Path]:
    created = []
    for svc in selected_services:
        for vol_path in svc.get("volumes", []):
            # Strip ./data/ prefix — paths are now relative to data_dir
            rel = vol_path.removeprefix("./data/").removeprefix("./")
            full = data_dir / rel
            full.mkdir(parents=True, exist_ok=True)
            created.append(full)
    return created
