#!/usr/bin/env bash
# One-time server setup for a fresh Ubuntu LTS server (DigitalOcean droplet). Run as root:
#
#   git clone https://github.com/VideoJames13/social-currency-bot.git /tmp/scb && bash /tmp/scb/deploy/setup.sh
#
# Safe to re-run: every step checks before changing anything.
set -euo pipefail

REPO_URL="https://github.com/VideoJames13/social-currency-bot.git"
APP_USER="bucks"
APP_HOME="/home/${APP_USER}"
APP_DIR="${APP_HOME}/social-currency-bot"
BACKUP_DIR="${APP_HOME}/backups"
PYTHON_VERSION="3.15"           # match the dev PC
TIMEZONE="America/New_York"     # matches config.toml; makes timers and logs read in local time

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
[[ $EUID -eq 0 ]] || { echo "Run this as root." >&2; exit 1; }

# Refuse to lock ourselves out: key-only SSH needs a key already installed.
if [[ ! -s /root/.ssh/authorized_keys ]]; then
  echo "No SSH key in /root/.ssh/authorized_keys; not disabling passwords. Aborting." >&2
  exit 1
fi

log "System updates and packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q git sqlite3 ufw unattended-upgrades curl ca-certificates

log "Timezone: ${TIMEZONE}"
timedatectl set-timezone "$TIMEZONE"

log "Swap: 1 GB safety net for memory spikes"
if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
  [[ -f /swapfile ]] || fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
echo 'vm.swappiness=10' > /etc/sysctl.d/99-bucks-swappiness.conf
sysctl -q -p /etc/sysctl.d/99-bucks-swappiness.conf

log "SSH: key login only"
cat > /etc/ssh/sshd_config.d/99-bucks-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
sshd -t
systemctl reload ssh 2>/dev/null || systemctl restart ssh

log "Firewall: allow SSH in, everything else in is blocked (the bot only connects out)"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw --force enable

log "Automatic security updates (reboots at 4:30am if an update needs it)"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
cat > /etc/apt/apt.conf.d/52bucks-unattended <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF

log "Log size cap (200 MB, 1 month)"
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/bucks.conf <<'EOF'
[Journal]
SystemMaxUse=200M
MaxRetentionSec=1month
EOF
systemctl restart systemd-journald

log "Bot user: ${APP_USER} (no sudo, no password)"
id "$APP_USER" &>/dev/null || useradd --create-home --shell /bin/bash "$APP_USER"
passwd -l "$APP_USER" >/dev/null

log "Code: ${APP_DIR}"
if [[ -d "$APP_DIR/.git" ]]; then
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
else
  sudo -u "$APP_USER" git clone -q "$REPO_URL" "$APP_DIR"
fi
sudo -u "$APP_USER" mkdir -p "$BACKUP_DIR"

log "Python ${PYTHON_VERSION} and dependencies (via uv)"
UV="$APP_HOME/.local/bin/uv"
if [[ ! -x "$UV" ]]; then
  sudo -u "$APP_USER" -H env UV_NO_MODIFY_PATH=1 sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi
sudo -u "$APP_USER" -H bash -euc "
  cd '$APP_DIR'
  '$UV' python install '$PYTHON_VERSION'
  '$UV' venv --python '$PYTHON_VERSION' --allow-existing .venv
  '$UV' pip install --python .venv/bin/python -q -r requirements.txt
"

log "Running the test suite"
sudo -u "$APP_USER" -H bash -c "cd '$APP_DIR' && .venv/bin/python -m unittest discover -q tests"

log "Secrets file (.env)"
if [[ ! -f "$APP_DIR/.env" ]]; then
  install -m 600 -o "$APP_USER" -g "$APP_USER" "$APP_DIR/.env.example" "$APP_DIR/.env"
fi
chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

log "Services: bot, nightly backup, restart watchdog"
bash "$APP_DIR/deploy/install-units.sh"

if grep -q '^DISCORD_TOKEN=..*' "$APP_DIR/.env"; then
  systemctl restart bucks-bot
  log "Done. Bot started. Follow its log with:  journalctl -u bucks-bot -f"
else
  log "Done, except the token: copy your .env to the server, then start the bot (see deploy/README.md)."
fi
free -h | sed -n '1,3p'
