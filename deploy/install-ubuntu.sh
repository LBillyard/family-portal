#!/usr/bin/env bash
# One-shot install for Ubuntu 22.04/24.04 (AWS EC2, Oracle Cloud, Hetzner, etc.)
# Run ON the server after copying/cloning the project to /opt/family-portal
#
#   sudo bash deploy/install-ubuntu.sh
#
set -euo pipefail

APP_DIR="/opt/family-portal"
PORT="${PORT:-8090}"
SERVICE="family-portal"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/install-ubuntu.sh"
  exit 1
fi

if [[ ! -f "$APP_DIR/server/main.py" ]]; then
  echo "Expected project at $APP_DIR — copy files first, e.g.:"
  echo "  scp -r . ubuntu@YOUR_IP:/opt/family-portal"
  exit 1
fi

echo "==> Ensuring swap (safety net for 1 GB RAM instances like t4g.micro)..."
if ! swapon --show 2>/dev/null | grep -q '/swapfile'; then
  if [[ ! -f /swapfile ]]; then
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
  fi
  swapon /swapfile || true
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl ufw

DEPLOY_USER="${SUDO_USER:-ubuntu}"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

echo "==> Python venv + dependencies..."
sudo -u "$DEPLOY_USER" bash -c "
  cd '$APP_DIR'
  python3 -m venv venv
  ./venv/bin/pip install -q --upgrade pip
  ./venv/bin/pip install -q -r requirements.txt
"

PUBLIC_IP="$(curl -sf http://checkip.amazonaws.com 2>/dev/null || curl -sf https://ifconfig.me 2>/dev/null || echo 'YOUR.PUBLIC.IP')"
ENV_FILE="$APP_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  SECRET="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')"
  cat > "$ENV_FILE" <<EOF
SECRET_KEY=${SECRET}
PUBLIC_URL=http://${PUBLIC_IP}:${PORT}
GOOGLE_REDIRECT_URI=http://${PUBLIC_IP}:${PORT}/api/auth/google/callback
TRUELAYER_REDIRECT_URI=http://${PUBLIC_IP}:${PORT}/api/banking/callback
EOF
  chown "$DEPLOY_USER:$DEPLOY_USER" "$ENV_FILE"
  echo "==> Created $ENV_FILE"
  echo "    Optional keys to fill in (see .env.example for details):"
  echo "      GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET      Calendar sync + Gmail receipts"
  echo "      TRUELAYER_CLIENT_ID / TRUELAYER_CLIENT_SECRET / TRUELAYER_ENV   Open Banking"
  echo "      TWILIO_* (or WHATSAPP_* for Meta)            WhatsApp digest + assistant"
  echo "      OPENROUTER_API_KEY                           AI assistant + holiday ideas"
  echo "      WEATHER_LATITUDE / WEATHER_LONGITUDE / WEATHER_LABEL   digest weather"
  echo "      SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM / SMTP_TLS / NOTIFY_EMAIL   email reminders"
  echo "      FAMILY_PORTAL_SEED_PASSWORD                  fresh-DB seed password (random + logged if unset)"
else
  echo "==> Keeping existing $ENV_FILE"
fi

mkdir -p "$APP_DIR/data"
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/data"
mkdir -p "$APP_DIR/backups"
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/backups"

echo "==> Installing systemd units (service + timers)..."
cp "$APP_DIR"/deploy/family-portal*.service "$APP_DIR"/deploy/family-portal*.timer /etc/systemd/system/
# Keep the app unit's port in sync with this install's PORT choice (unit ships with 8090).
sed -i -E "s/--port [0-9]+/--port ${PORT}/" "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

echo "==> Enabling timers (07:00 digest, 07:30 inbox scan, hourly sync, 15-min task reminders, 08/13/18 reminders, 20:00 evening, Sun 18:00 weekly finance, 03:00 backup)..."
for TIMER in family-portal-digest.timer family-portal-inbox.timer family-portal-sync.timer \
             family-portal-task-reminders.timer family-portal-reminders.timer \
             family-portal-evening.timer family-portal-weekly.timer \
             family-portal-backup.timer; do
  systemctl enable --now "$TIMER"
done

echo "==> Firewall (ufw) — opening port $PORT..."
ufw allow OpenSSH >/dev/null 2>&1 || true
ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
echo "y" | ufw enable >/dev/null 2>&1 || true

sleep 2
if systemctl is-active --quiet "$SERVICE"; then
  echo ""
  echo "=============================================="
  echo "  Family Portal is running"
  echo "  URL: http://${PUBLIC_IP}:${PORT}"
  echo "  Logins: lbillyard@gmail.com / lebillyard@gmail.com"
  echo "  Fresh-DB password: FAMILY_PORTAL_SEED_PASSWORD if set,"
  echo "  else auto-generated + logged (journalctl -u ${SERVICE})"
  echo "  Update Google OAuth redirect URI to match PUBLIC_URL"
  echo "=============================================="
else
  echo "Service failed to start — check: journalctl -u $SERVICE -n 50"
  exit 1
fi
