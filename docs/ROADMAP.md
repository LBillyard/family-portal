# Roadmap & known gaps

Prioritized work for humans and AI agents continuing **The Hub**. Verify against
the code — this file is kept roughly current but the source is the truth.

## Done (was P0/P1/P2)

- ✅ Password change flow; seeded passwords rotated off `family123` on the live box
- ✅ HTTPS in production (Caddy + Let's Encrypt at `hub.squirrelinvestments.co.uk`)
- ✅ OAuth tokens encrypted at rest
- ✅ XSS: dynamic strings escaped via `esc()`; CSP + HSTS headers
- ✅ Login rate limiting (429 after repeated failures)
- ✅ AI tool confirmations on-web; WhatsApp assistant acts immediately by design
- ✅ **argon2id** password hashing with PBKDF2 fallback + transparent upgrade on login
- ✅ **CSV formula-injection guard** on finance export
- ✅ **Two-way Google Calendar** write-back, targetable per connected calendar
- ✅ **Automated tests** — `pytest` suite in `tests/` (auth, weather, finance, API smoke)
- ✅ Export finances to CSV
- ✅ Weather widget + holiday-aware forecast; hourly auto-sync (Google + banks)
- ✅ **Gmail receipt ingestion** — scan inbox for receipts → OCR → reviewable drafts
- ✅ **Task management** — untick complete, reassign owner (optional WhatsApp ping), due date, separate reminder date/time (`family-portal-task-reminders.timer`, every 15 min)

## P2 — Features (open)

- [ ] **Push notifications** — appointment/bill reminders (web push)
- [ ] **Vault tab search box** — global search already indexes document name/notes/category; remaining work is a dedicated filter box on the Vault tab itself
- [ ] **Holiday booking workflow** — flights/hotels checklist automation
- [ ] Gmail receipts: support PDF attachments (needs a PDF→image step) — currently images only
- [ ] Bank disconnect ownership — optional per-user check

## P3 — Polish

- [ ] Dark mode toggle
- [ ] Mobile nav improvements
- [ ] Expand test coverage (assistant tool-calls, bank sync, calendar sync)
- [ ] `pip-audit` in CI (dependency already in `requirements-dev.txt`)

## Ops notes

- Deploy = `scp` changed files to `/opt/family-portal` (the box is NOT a git repo) + `systemctl restart family-portal`. Bump `?v=` in `index.html` **and** the `CACHE` constant in `sw.js` on every frontend deploy.
- Timers on the box: `family-portal-digest.timer` (07:00 digest), `family-portal-sync.timer` (hourly Google + bank sync), `family-portal-task-reminders.timer` (every 15 min, task reminder WhatsApp pings).
- `argon2-cffi` must be `pip install`ed into the box venv (it's in `requirements.txt`); without it, auth safely falls back to PBKDF2.
- Gmail scope (`gmail.readonly`) was added to `SCOPES` — existing Google connections must be **re-connected** to grant it before email receipt scanning works.
