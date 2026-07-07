# Family Portal — Deployment Runbook

**Status:** Infrastructure and scripts are ready. **Do not run deploy until you have reviewed security settings and changed default passwords.**

This guide covers AWS EC2 deployment (cheapest layout) and manual Ubuntu install. The app listens on port **8090**.

---

## Pre-deploy checklist

- [ ] Decide the seed password: set `FAMILY_PORTAL_SEED_PASSWORD` in `.env` before first start, or grab the auto-generated one logged at seed time (`journalctl -u family-portal`), then rotate via Settings → change password
- [ ] Generate `SECRET_KEY`: `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] Create [Google OAuth credentials](https://console.cloud.google.com/apis/credentials) with redirect URI matching your public URL
- [ ] Add `OPENROUTER_API_KEY` if using AI holiday ideas
- [ ] Restrict SSH (`AllowedSshCidr`) to your home IP in CloudFormation parameters
- [ ] Consider `-CreateElasticIp` so the public IP survives reboots

---

## Option A — AWS one-command deploy (Windows)

Prerequisites: AWS CLI configured, EC2 key pair exists.

```powershell
cd "C:\Users\Luke\Desktop\Cursor Projects\The Family Portal"

# Stack only (no code upload):
.\deploy\aws\deploy.ps1 -KeyName "your-key-name" -SkipUpload

# Full deploy with upload:
.\deploy\aws\deploy.ps1 -KeyName "your-key-name" -KeyPath "C:\path\to\your-key.pem" -CreateElasticIp
```

Parameters:

| Parameter | Default | Notes |
|-----------|---------|-------|
| `-StackName` | `family-portal` | CloudFormation stack name |
| `-Region` | `eu-west-2` | AWS region |
| `-AppPort` | `8090` | Must match security group + app |
| `-AllowedSshCidr` | `0.0.0.0/0` | **Restrict in production** |
| `-AllowedAppCidr` | `0.0.0.0/0` | **Restrict in production** |

After stack creation, note the **PortalUrl** output.

### Post-deploy configuration

SSH into the instance and edit `/opt/family-portal/.env`:

```bash
sudo nano /opt/family-portal/.env
```

Set at minimum:

```env
SECRET_KEY=your-generated-secret
PUBLIC_URL=http://YOUR_ELASTIC_IP:8090
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://YOUR_ELASTIC_IP:8090/api/auth/google/callback
OPENROUTER_API_KEY=...
```

Restart:

```bash
sudo systemctl restart family-portal
sudo systemctl status family-portal
journalctl -u family-portal -f
```

---

## Option B — Manual upload to existing EC2

```powershell
ssh -i YOUR_KEY.pem ubuntu@YOUR_IP "mkdir -p /tmp/family-upload"
scp -i YOUR_KEY.pem -r server shared deploy requirements.txt ubuntu@YOUR_IP:/tmp/family-upload/
```

On the server:

```bash
sudo mkdir -p /opt/family-portal
sudo rsync -a /tmp/family-upload/ /opt/family-portal/
sudo chown -R ubuntu:ubuntu /opt/family-portal
sudo bash /opt/family-portal/deploy/install-ubuntu.sh
```

---

## Option C — Any Ubuntu VPS (no AWS)

1. Clone/copy project to `/opt/family-portal`
2. Copy `.env.example` → `.env` and fill values
3. Run `sudo bash deploy/install-ubuntu.sh`

The install script:

- Creates Python venv and installs `requirements.txt`
- Generates `.env` with random `SECRET_KEY` plus `PUBLIC_URL`, `GOOGLE_REDIRECT_URI` and `TRUELAYER_REDIRECT_URI` if missing
- Installs `family-portal.service` **and** the three timers (`family-portal-digest`, `family-portal-sync`, `family-portal-task-reminders`) and enables them
- Opens the app port in ufw (default 8090; override with `PORT=` — the script patches the systemd unit to match)

---

## Routine deploys (updating the live box)

The box is **NOT a git repo** — a deploy is just copying changed files and restarting:

```powershell
ssh -i YOUR_KEY.pem ubuntu@YOUR_IP "mkdir -p /tmp/family-upload"
scp -i YOUR_KEY.pem -r server shared ubuntu@YOUR_IP:/tmp/family-upload/
ssh -i YOUR_KEY.pem ubuntu@YOUR_IP "sudo rsync -a /tmp/family-upload/ /opt/family-portal/ && sudo systemctl restart family-portal"
```

Checklist for **every** deploy:

- [ ] **Frontend changed?** Bump the `?v=` cache-bust on the script/style links in `server/static/index.html` **and** the `CACHE` constant in `server/static/sw.js` — otherwise the service worker keeps serving stale assets
- [ ] `sudo systemctl restart family-portal` after files land
- [ ] Unit/timer file changed? Copy it to `/etc/systemd/system/`, then `sudo systemctl daemon-reload` and re-enable

Background timers on the box (installed by `install-ubuntu.sh`):

| Timer | Schedule | Job |
|-------|----------|-----|
| `family-portal-digest.timer` | 07:00 Europe/London | WhatsApp morning digest |
| `family-portal-sync.timer` | hourly | Google Calendar + bank sync |
| `family-portal-task-reminders.timer` | every 15 min | task reminder WhatsApp pings |

Check them with `systemctl list-timers 'family-portal-*'`.

---

## Architecture (AWS)

```
Internet
    │
    ▼
┌─────────────────┐
│ EC2 t4g.micro   │  Ubuntu 24.04 (arm64 / Graviton)
│ 1 GB RAM + 2 GB │  FastAPI + uvicorn
│ swap, port 8090 │  SQLite → /opt/family-portal/data/family.db
└─────────────────┘
    │
    └── EBS gp3 (8 GB default) — database persists on volume
```

No RDS, ALB, or NAT gateway. **ARM/Graviton (`t4g`) is ~30–40% cheaper than the equivalent Intel `t3` for identical capacity** — all Python deps ship arm64 wheels, so nothing else changes.

Approx. monthly cost in eu-west-2 (excl. UK VAT):

| Item | Cost |
|------|------|
| t4g.micro compute (on-demand) | ~$6.15/mo |
| Public IPv4 address (mandatory since Feb 2024, $0.005/hr) | ~$3.65/mo |
| EBS gp3 8 GB | ~$0.70/mo |
| **Total** | **~$10.5/mo** (+ 20% UK VAT ≈ ~$13/mo) |

`install-ubuntu.sh` adds a 2 GB swap file so concurrent 10 MB receipt/media uploads can't OOM the 1 GB box. Size down to `t4g.nano` (0.5 GB, ~$3/mo compute) if you want it cheaper — swap makes that viable for 2 users, with less headroom.

Optional: attach Elastic IP for a stable IP/OAuth redirect (same $3.65/mo IPv4 charge, not additional).

---

## HTTPS (recommended before production)

The app serves plain HTTP. For HTTPS:

1. Point a domain A record to your Elastic IP
2. Install Caddy or nginx as reverse proxy on the same instance
3. Update `PUBLIC_URL` and `GOOGLE_REDIRECT_URI` to `https://your.domain`
4. Open ports 80/443 in security group instead of (or in addition to) 8090

Example Caddy snippet (not included in repo):

```
your.domain {
    reverse_proxy localhost:8090
}
```

---

## Web push setup

Browser push notifications reach phones even outside the WhatsApp 24-hour reply
window, so they're the reliable channel for reminders. Push requires the
**HTTPS** site above (browsers refuse the Push API over plain HTTP).

1. Generate one VAPID keypair on the server, inside the app venv:

   ```bash
   cd /opt/family-portal
   ./venv/bin/python deploy/gen-vapid.py
   ```

2. Paste the three printed lines (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
   `VAPID_SUBJECT`) into `/opt/family-portal/.env`.

3. Restart: `sudo systemctl restart family-portal`

4. Each user opens the HTTPS site, goes to **Settings → Enable notifications**,
   and accepts the browser permission prompt.

Generate the keypair **once** and keep it — rotating `VAPID_*` invalidates every
existing subscription, so users would have to re-enable notifications.

---

## Backup

SQLite database:

```bash
sudo cp /opt/family-portal/data/family.db /opt/family-portal/data/family.db.bak.$(date +%F)
```

For automated backups, cron + `aws s3 cp` to a private S3 bucket is sufficient for a two-user household app.

---

## Rollback

```powershell
aws cloudformation delete-stack --stack-name family-portal --region eu-west-2
```

This terminates the EC2 instance and releases the Elastic IP (if created). **Back up `family.db` first.**

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| 502 / connection refused | `journalctl -u family-portal -n 50` |
| Google OAuth redirect mismatch | `GOOGLE_REDIRECT_URI` must exactly match Google Console |
| AI generate fails | Check `OPENROUTER_API_KEY`; verify model name |
| CSV import 400 | Ensure CSV has date + description + amount columns |
| Session lost on restart | Set stable `SECRET_KEY` in `.env` |

---

## What was intentionally not deployed

Per project scope, **no AWS resources were created** during the build phase. All deploy artifacts live in `deploy/` for you to run when ready.

See also: [BUILD.md](./BUILD.md) for architecture and API details.
