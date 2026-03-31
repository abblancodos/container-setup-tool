# infra-setup

Configurador interactivo de stack Docker. Te lleva de la mano para generar
`docker-compose.yml`, `.env`, y vhosts de nginx sin andar en laberintos de menús.

## Uso

```bash
pip install -r requirements.txt
python3 setup.py
```

## Flujo

1. **Directorio** — elegís dónde instalar. Avisa si necesitás sudo.
2. **Servicios** — si ya hay un stack lo detecta y te deja modificarlo.
   Si no hay nada, configuración desde cero.
3. **Configuración** — pregunta puertos, contraseñas, dominios. Enter = valor predeterminado.
4. **Generación** — crea `docker-compose.yml`, `.env`, vhosts nginx, y directorios `data/`.
5. **Resumen** — te muestra el comando para arrancar y las notas de cada servicio.

## Servicios incluidos

| ID       | Descripción                              |
|----------|------------------------------------------|
| gitea    | Servidor Git + Actions runner            |
| postgres | PostgreSQL standalone                    |
| wikijs   | Wiki.js con sync a Gitea                 |
| dbsync   | Motor de sync PostgreSQL + frontend      |
| nginx    | Reverse proxy con vhosts por servicio    |

## Agregar un servicio custom

Al seleccionar **[+] Agregar servicio custom...** el programa te hace las preguntas
necesarias y guarda la plantilla en `services/templates/<id>.yaml`.

Para que otros la tengan disponible:

```bash
git add services/templates/
git commit -m "add <id> template"
git push
```

## Agregar un servicio builtin

Creá `services/<nombre>.py` con un dict `SERVICE` siguiendo la misma estructura
que los existentes, y agregá `"<nombre>"` a `BUILTIN_SERVICES` en `setup.py`.
