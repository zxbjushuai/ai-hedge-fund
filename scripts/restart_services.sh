#!/usr/bin/env bash
set -euo pipefail

sudo -n systemctl restart aihf-backend
sleep 2
curl -fsS http://127.0.0.1:8000/health
echo

if [ "${1:-}" = "--frontend" ]; then
    sudo -n systemctl restart aihf-frontend
fi
