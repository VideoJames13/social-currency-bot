#!/usr/bin/env bash
# Deploy the latest code from GitHub. Run as root on the server:
#   bash /home/bucks/social-currency-bot/deploy/update.sh
# Backs up first, and only restarts the bot if the tests pass.
set -euo pipefail
APP_USER="bucks"
APP_DIR="/home/${APP_USER}/social-currency-bot"
UV="/home/${APP_USER}/.local/bin/uv"
log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
[[ $EUID -eq 0 ]] || { echo "Run this as root." >&2; exit 1; }
as_bot() { sudo -u "$APP_USER" -H bash -euc "cd '$APP_DIR' && $1"; }

log "Backing up the database first"
sudo -u "$APP_USER" bash "$APP_DIR/deploy/backup.sh"

before="$(as_bot 'git rev-parse --short HEAD')"
log "Pulling latest code"
as_bot 'git pull --ff-only'
after="$(as_bot 'git rev-parse --short HEAD')"
if [[ "$before" == "$after" ]]; then
  log "Already up to date ($after). Nothing to do."
  exit 0
fi
as_bot 'git log --oneline '"$before..$after"

log "Installing dependencies"
as_bot "'$UV' pip install --python .venv/bin/python -q -r requirements.txt"

log "Running tests"
if ! as_bot '.venv/bin/python -m unittest discover -q tests'; then
  echo "Tests FAILED. Rolling the code back to $before; the bot was not restarted." >&2
  as_bot "git reset -q --hard '$before'"
  as_bot "'$UV' pip install --python .venv/bin/python -q -r requirements.txt"
  exit 1
fi

log "Refreshing services and restarting the bot"
bash "$APP_DIR/deploy/install-units.sh"
systemctl restart bucks-bot
sleep 5
systemctl --no-pager --lines=15 status bucks-bot || true
log "Updated $before -> $after"
