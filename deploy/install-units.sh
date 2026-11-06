#!/usr/bin/env bash
# Installs/refreshes the systemd units from deploy/systemd/. Run as root (setup.sh and
# update.sh call this).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
install -m 644 "$HERE"/systemd/*.service "$HERE"/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q bucks-bot.service bucks-bot-backup.timer bucks-bot-watchdog.timer
systemctl start bucks-bot-backup.timer bucks-bot-watchdog.timer
