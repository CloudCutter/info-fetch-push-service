#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/info-fetch-push-service}"
SERVICE_NAME="${SERVICE_NAME:-info-fetch-push}"
TARBALL_PATH="${TARBALL_PATH:-}"

if [[ -z "${TARBALL_PATH}" ]]; then
  if [[ -f "/root/info-fetch-push-service-server.tar.gz" ]]; then
    TARBALL_PATH="/root/info-fetch-push-service-server.tar.gz"
  elif [[ -f "/root/info-fetch-push-service-deploy.tar.gz" ]]; then
    TARBALL_PATH="/root/info-fetch-push-service-deploy.tar.gz"
  fi
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run this script as root."
  exit 1
fi

if [[ ! -f "${TARBALL_PATH}" && ! -f "${APP_DIR}/pyproject.toml" ]]; then
  echo "Deployment tarball not found and app directory is incomplete."
  echo "Expected tarball at: /root/info-fetch-push-service-server.tar.gz"
  echo "Or ensure the project has already been extracted to: ${APP_DIR}"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y python3 python3-venv python3-pip curl ca-certificates

mkdir -p "${APP_DIR}"

if [[ ! -f "${APP_DIR}/pyproject.toml" ]]; then
  tar -xzf "${TARBALL_PATH}" -C "${APP_DIR}"
fi

cd "${APP_DIR}"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m playwright install chromium
python -m playwright install-deps chromium

install -Dm644 deploy/systemd/info-fetch-push.service "/etc/systemd/system/${SERVICE_NAME}.service"
sed -i "s|/opt/info-fetch-push-service|${APP_DIR}|g" "/etc/systemd/system/${SERVICE_NAME}.service"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo
echo "Bootstrap completed."
echo "Review ${APP_DIR}/.env before starting the service if needed."
echo "Start service: systemctl start ${SERVICE_NAME}"
echo "Check status:  systemctl status ${SERVICE_NAME}"
echo "View logs:     journalctl -u ${SERVICE_NAME} -f"
