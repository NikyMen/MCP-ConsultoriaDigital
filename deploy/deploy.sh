#!/usr/bin/env bash
# Script de deploy. Corré esto en el VPS para actualizar el código y reiniciar.
# Asume que el repo está clonado en /opt/mcp-consultoria.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/mcp-consultoria}"
SERVICE="${SERVICE:-consultoria-mcp}"

cd "$APP_DIR"

echo "==> git pull"
git pull --ff-only

echo "==> venv + deps"
if [[ ! -d .venv ]]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "==> restart $SERVICE"
sudo systemctl restart "$SERVICE"
sudo systemctl status --no-pager "$SERVICE" || true

echo "==> OK"
