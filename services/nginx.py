SERVICE = {
    "id": "nginx",
    "name": "Nginx",
    "description": "Reverse proxy",
    "questions": [
        {"key": "BASE_DOMAIN", "label": "Base domain (e.g. myserver.com or IP)", "default": "localhost"},
    ],
    "compose": {
        "nginx": {
            "image": "nginx:bookworm",
            "restart": "unless-stopped",
            "ports": ["80:80", "443:443"],
            "volumes": [
                "./nginx/conf.d:/etc/nginx/conf.d:ro",
                "./nginx/ssl:/etc/nginx/ssl:ro",
                "./data/nginx-logs:/var/log/nginx",
            ],
        }
    },
    "nginx_upstream":   None,
    "nginx_domain_var": None,
    "volumes": ["./data/nginx-logs", "./nginx/conf.d", "./nginx/ssl"],
    "post_install_note": (
        "ℹ  Vhosts generated at ./nginx/conf.d/\n"
        "   For SSL: copy certificates to ./nginx/ssl/ or use Certbot."
    ),
}
