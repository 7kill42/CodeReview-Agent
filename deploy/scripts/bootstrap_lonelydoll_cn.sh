#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="/root/project/CodeReview-Agent"
VENV_DIR="${PROJECT_DIR}/.venv"
ENV_FILE="${PROJECT_DIR}/.env.production"
ENV_TEMPLATE="${PROJECT_DIR}/deploy/env/production.lonelydoll.cn.example"
NGINX_SRC="${PROJECT_DIR}/deploy/nginx/lonelydoll.cn.conf"
NGINX_DST="/etc/nginx/sites-available/lonelydoll.cn.conf"
NGINX_LINK="/etc/nginx/sites-enabled/lonelydoll.cn.conf"
API_SERVICE="codereview-agent-api.service"
UI_SERVICE="codereview-agent-ui.service"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
SKIP_CERTBOT="${SKIP_CERTBOT:-0}"

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "Please run this script as root." >&2
        exit 1
    fi
}

require_project() {
    if [[ ! -d "${PROJECT_DIR}" ]]; then
        echo "Project directory not found: ${PROJECT_DIR}" >&2
        exit 1
    fi
}

install_packages() {
    apt-get update
    apt-get install -y \
        python3 \
        python3-venv \
        python3-pip \
        nginx \
        certbot \
        python3-certbot-nginx \
        docker.io \
        curl
}

prepare_venv() {
    if [[ ! -d "${VENV_DIR}" ]]; then
        python3 -m venv "${VENV_DIR}"
    fi

    "${VENV_DIR}/bin/pip" install --upgrade pip
    "${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"
}

prepare_env_file() {
    if [[ ! -f "${ENV_FILE}" ]]; then
        cp "${ENV_TEMPLATE}" "${ENV_FILE}"
        echo "Created ${ENV_FILE}. Fill in secrets before relying on production traffic."
    else
        echo "Keeping existing ${ENV_FILE}"
    fi
}

start_data_services() {
    systemctl enable --now docker

    if ! docker ps -a --format '{{.Names}}' | grep -qx 'codereview-postgres'; then
        docker run -d \
            --name codereview-postgres \
            -p 5432:5432 \
            -e POSTGRES_PASSWORD=postgres \
            -e POSTGRES_DB=codereview \
            postgres:15
    else
        docker start codereview-postgres >/dev/null || true
    fi

    if ! docker ps -a --format '{{.Names}}' | grep -qx 'codereview-redis'; then
        docker run -d \
            --name codereview-redis \
            -p 6379:6379 \
            redis:7
    else
        docker start codereview-redis >/dev/null || true
    fi
}

install_systemd_services() {
    cp "${PROJECT_DIR}/deploy/systemd/${API_SERVICE}" /etc/systemd/system/
    cp "${PROJECT_DIR}/deploy/systemd/${UI_SERVICE}" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now codereview-agent-api
    systemctl enable --now codereview-agent-ui
}

install_nginx() {
    cp "${NGINX_SRC}" "${NGINX_DST}"

    if [[ ! -L "${NGINX_LINK}" ]]; then
        ln -s "${NGINX_DST}" "${NGINX_LINK}"
    fi

    nginx -t
    systemctl enable --now nginx
    systemctl reload nginx
}

maybe_issue_cert() {
    if [[ "${SKIP_CERTBOT}" == "1" ]]; then
        echo "Skipping certbot because SKIP_CERTBOT=1"
        return
    fi

    if [[ -z "${CERTBOT_EMAIL}" ]]; then
        echo "Skipping certbot because CERTBOT_EMAIL is not set."
        echo "Run this later:"
        echo "  CERTBOT_EMAIL=you@example.com ${PROJECT_DIR}/deploy/scripts/bootstrap_lonelydoll_cn.sh"
        return
    fi

    certbot --nginx \
        --non-interactive \
        --agree-tos \
        --redirect \
        -m "${CERTBOT_EMAIL}" \
        -d lonelydoll.cn \
        -d www.lonelydoll.cn \
        -d api.lonelydoll.cn \
        -d app.lonelydoll.cn
}

print_next_steps() {
    cat <<'EOF'

Bootstrap finished.

Recommended checks:
  systemctl status codereview-agent-api
  systemctl status codereview-agent-ui
  curl http://127.0.0.1:8000/health
  curl -I http://app.lonelydoll.cn

Important:
  Edit /root/project/CodeReview-Agent/.env.production with real secrets if you have not already.
  GitHub webhook URL should be: https://api.lonelydoll.cn/webhook/github
EOF
}

main() {
    require_root
    require_project
    install_packages
    prepare_venv
    prepare_env_file
    start_data_services
    install_systemd_services
    install_nginx
    maybe_issue_cert
    print_next_steps
}

main "$@"
