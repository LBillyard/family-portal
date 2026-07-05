# Roadmap & known gaps

Prioritized work for humans and AI agents continuing Family Portal.

## P0 — Before public internet exposure

- [ ] **Change default passwords** — seeded `family123` in `database.py`; add `/api/auth/change-password` or reset flow
- [ ] **Strong SECRET_KEY** — required when `ENV=production` (enforced in `main.py`)
- [ ] **HTTPS** — terminate TLS at Caddy, nginx, or Cloudflare Tunnel; set `PUBLIC_URL=https://...`
- [ ] **Encrypt OAuth tokens** — Google + TrueLayer tokens currently plaintext in SQLite

## P1 — Security hardening

- [ ] **Full XSS fix** — escape all dynamic strings in `app.js` `innerHTML` (only `esc()` in toasts + assistant today)
- [ ] **Login rate limiting** — slowapi or nginx `limit_req`
- [ ] **AI tool confirmations** — confirm before bills, transactions, destructive actions
- [ ] **Restrict AWS CIDRs** — `deploy/aws/cloudformation.yaml` defaults to `0.0.0.0/0`

## P2 — Features

- [ ] **Two-way Google Calendar** — write portal events back to Google
- [ ] **Push notifications** — appointment/bill reminders
- [ ] **Bank disconnect ownership** — optional per-user check
- [ ] **Vault search** — full-text on document names/notes
- [ ] **Holiday booking workflow** — flights, hotels checklist automation
- [ ] **Automated tests** — pytest for auth, CRUD, assistant tools

## P3 — Polish

- [ ] Argon2/bcrypt instead of PBKDF2
- [ ] Dark mode toggle
- [ ] Mobile nav improvements
- [ ] Export finances to CSV

## Completed (reference)

- Core CRUD + dashboard
- Google Calendar OAuth + sync
- TrueLayer Open Banking (Starling, Revolut, Amex, Virgin)
- Document vault with file uploads
- AI assistant with OpenRouter tool calling
- PWA manifest + service worker
- Security headers, session rotation, production mode, vault download hardening
