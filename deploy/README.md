# Running the bot on the server

Server layout (Ubuntu LTS, set up by `setup.sh`):

| What | Where |
| --- | --- |
| Code | `/home/bucks/social-currency-bot` (git clone, runs as user `bucks`) |
| Secrets | `/home/bucks/social-currency-bot/.env` (mode 600, never in git) |
| Database | `/home/bucks/social-currency-bot/bucks.db` |
| Backups | `/home/bucks/backups/bucks-YYYY-MM-DD_HHMM.db.gz` (newest 14, nightly 3:30am ET) |
| Service | `bucks-bot.service` (+ `bucks-bot-backup.timer`, `bucks-bot-watchdog.timer`) |

Replace `SERVER` below with the server's IP address. Commands marked **PC** run in
PowerShell on your computer; everything else runs on the server after `ssh root@SERVER`.

> **Never run the bot on your PC and the server at the same time.** Both would receive
> every event and pay everyone twice.

## First-time setup

```bash
git clone https://github.com/VideoJames13/social-currency-bot.git /tmp/scb && bash /tmp/scb/deploy/setup.sh
```

Then copy your secrets file up (**PC**, from the project folder) and start the bot:

```powershell
scp .env root@SERVER:/home/bucks/social-currency-bot/.env
ssh root@SERVER "chown bucks:bucks /home/bucks/social-currency-bot/.env && chmod 600 /home/bucks/social-currency-bot/.env && systemctl restart bucks-bot"
```

## Everyday commands

| Task | Command |
| --- | --- |
| Live log | `journalctl -u bucks-bot -f` (Ctrl+C to stop watching) |
| Last hour of log | `journalctl -u bucks-bot --since "1 hour ago"` |
| Status | `systemctl status bucks-bot` |
| Restart | `systemctl restart bucks-bot` |
| Stop (stays stopped, watchdog won't restart it) | `systemctl stop bucks-bot` |
| Start | `systemctl start bucks-bot` |
| Deploy latest code from GitHub | `bash /home/bucks/social-currency-bot/deploy/update.sh` |
| Back up right now | `sudo -u bucks bash /home/bucks/social-currency-bot/deploy/backup.sh` |
| List backups | `ls -lh /home/bucks/backups` |
| Memory / disk | `free -h` / `df -h /` |

**Don't edit `config.toml` on the server.** Change it on your PC, commit and push, then
run `update.sh`. Local edits on the server would block `git pull`. `.env` is the only file you edit on the server
(`nano /home/bucks/social-currency-bot/.env`, then `systemctl restart bucks-bot`).

## Restore a backup

```bash
systemctl stop bucks-bot
cd /home/bucks/social-currency-bot
sudo -u bucks mv bucks.db "bucks.db.before-restore-$(date +%F_%H%M)"
rm -f bucks.db-wal bucks.db-shm
gunzip -c /home/bucks/backups/bucks-2026-11-06_0330.db.gz | sudo -u bucks tee bucks.db >/dev/null
systemctl start bucks-bot
```

## Full reset (fresh launch, everyone gets the starting balance again)

```bash
systemctl stop bucks-bot
cd /home/bucks/social-currency-bot
sudo -u bucks mv bucks.db "bucks.db.reset-$(date +%F_%H%M)"
rm -f bucks.db-wal bucks.db-shm
systemctl start bucks-bot
```

## Copy a backup to your PC (PC)

```powershell
scp root@SERVER:/home/bucks/backups/bucks-2026-11-06_0330.db.gz .
```

## What protects what

- **Crash loop:** systemd allows 5 starts per 10 minutes, then gives up; the watchdog
  retries every 30 minutes. Keeps logins far below Discord's daily limit (which would
  reset the token).
- **Memory spikes:** 1 GB swap file.
- **Disk filling:** logs capped at 200 MB / 1 month; 14 backups kept.
- **Security:** SSH keys only, firewall allows only SSH in, automatic security updates
  (reboots at 4:30am ET when needed; the bot starts on boot), bot runs as an
  unprivileged user that can only write to its own folder.
- **Losing the server:** DigitalOcean weekly backups (enable in the droplet's Backups tab)
  plus the nightly database backups, which you can copy to your PC any time.
