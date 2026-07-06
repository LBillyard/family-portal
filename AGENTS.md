# AGENTS.md — AI continuation guide

This file is the **primary handoff document** for Claude, Cursor, or other AI agents continuing work on **Family Portal**. Read this before making changes.

## Project summary

**Family Portal** is a household hub web app for **two adults** (Luke & Partner). It manages calendar, finances, appointments, holidays, tasks, document vault, and an **AI assistant** wired into household actions via OpenRouter tool calling.

| Item | Value |
|------|-------|
| Owner GitHub | [github.com/lbillyard](https://github.com/lbillyard) |
| Stack | FastAPI + SQLite + vanilla HTML/CSS/JS (no frontend build) |
| Port | **8090** |
| Theme | Navy `#0f1d32` + teal `#00a89e` (matches Pokemon scraper aesthetic) |
| Auth | Session cookies; argon2id passwords (PBKDF2 fallback, auto-upgrades on login) |
| Data | `data/family.db` (gitignored; override path with `FAMILY_PORTAL_DB`), uploads in `data/uploads/` |
| Tests | `pytest` (see `tests/`, `requirements-dev.txt`) |

## Quick start (local)

```bash
git clone https://github.com/lbillyard/family-portal.git
cd family-portal
python -m pip install -r requirements.txt
cp .env.example .env   # fill in secrets locally — never commit .env
python -m server.main
```

Open **http://localhost:8090**. Sign in with the seeded household accounts (`lbillyard@gmail.com` / `lebillyard@gmail.com`); on a fresh DB the password comes from `FAMILY_PORTAL_SEED_PASSWORD`, or is auto-generated and logged once at seed time (see `server/database.py` `_seed()`).

## Repository layout

```
family-portal/
├── AGENTS.md              ← YOU ARE HERE — start here
├── README.md              ← User-facing overview
├── docs/
│   ├── BUILD.md           ← Architecture, phases, API tables
│   ├── DEPLOY.md          ← AWS / Ubuntu deploy runbook
│   └── ROADMAP.md         ← Planned work & known gaps
├── server/
│   ├── main.py            ← FastAPI app, sessions, security headers, ENV=production checks
│   ├── auth.py            ← Password hash / verify
│   ├── database.py        ← SQLite schema, CRUD, migrations, seed
│   ├── api/routes.py      ← All REST + OAuth callbacks
│   ├── services/
│   │   ├── assistant.py   ← AI chat + OpenRouter tool calling
│   │   ├── dashboard.py   ← Home tab aggregation
│   │   ├── documents.py   ← Vault file helpers
│   │   ├── google_calendar.py  ← calendar sync + write-back; SCOPES incl. gmail.readonly
│   │   ├── gmail_receipts.py    ← scan inbox for receipts → OCR drafts
│   │   ├── open_banking.py  ← TrueLayer (Starling, Revolut, Amex, Virgin)
│   │   ├── weather.py       ← Open-Meteo forecast + holiday-aware location
│   │   ├── openrouter.py    ← Holiday ideas + model allowlist
│   │   ├── receipts.py      ← OpenRouter vision receipt OCR
│   │   └── csv_import.py
│   ├── jobs/
│   │   ├── morning_digest.py  ← 07:00 WhatsApp digest (systemd timer)
│   │   └── auto_sync.py       ← hourly Google + bank sync (systemd timer)
│   └── static/
│       ├── index.html     ← Single-page shell
│       ├── app.js         ← Tab UI, API client, AI chat panel
│       └── style.css
├── shared/schemas.py      ← Pydantic request models
├── tests/                 ← pytest suite (isolated DB via FAMILY_PORTAL_DB)
├── deploy/                ← systemd units, CloudFormation, install scripts
├── requirements.txt / requirements-dev.txt
└── .env.example           ← Template only — no real secrets
```

## Architecture (mental model)

```
Browser (app.js)
    │  fetch /api/*  credentials: include
    ▼
FastAPI (routes.py) ── require_user() session check
    │
    ├── database.py  (SQLite CRUD)
    └── services/    (Google, TrueLayer, OpenRouter, assistant tools)
```

- **No ORM** — raw parameterized SQL in `database.py`.
- **No React/Vue** — all UI is rendered in `app.js` via template strings + `innerHTML`.
- **Integrations are optional** — app runs without Google/OpenRouter/TrueLayer keys; endpoints return 503 with clear messages.

## Feature status

| Feature | Status | Key files |
|---------|--------|-----------|
| Dashboard / Home | ✅ Done | `dashboard.py`, `app.js` renderHome* |
| Calendar CRUD | ✅ Done | `database.py`, `/api/events` |
| Google Calendar sync | ✅ OAuth + pull | `google_calendar.py` |
| Finances (bills, txns, budgets) | ✅ Done | `database.py`, `/api/finances` |
| Open Banking (TrueLayer) | ✅ Done | `open_banking.py`, `/api/banking/*` |
| CSV import | ✅ Done | `csv_import.py` |
| Appointments | ✅ Done | `/api/appointments` |
| Holidays + AI ideas | ✅ Done | `openrouter.py` |
| Document Vault (uploads) | ✅ Done | `documents.py`, `/api/documents/upload` |
| AI Assistant (tool calling) | ✅ Done | `assistant.py`, `/api/assistant/*`, chat FAB in UI |
| PWA (manifest + SW) | ✅ Done | `manifest.json`, `sw.js` |
| Change password | ✅ Done | `POST /api/auth/change-password` (`routes.py`), Settings tab in `app.js` |
| Token encryption at rest | ✅ Done | Google/bank tokens encrypted (Fernet, key from `SECRET_KEY`) in `database.py` |
| Full XSS hardening | ⚠️ Partial | `esc()` used in assistant + toasts; most `innerHTML` still unescaped |
| Login rate limiting | ✅ Done | 429 after repeated failures (`routes.py` login) |
| Automated tests | ✅ Done | pytest suite in `tests/` — run `python -m pytest` |
| HTTPS / production deploy | ✅ Live | AWS EC2 box, systemd `family-portal` + 3 timers (see `deploy/`, docs/DEPLOY.md) |

See **docs/ROADMAP.md** for prioritized next steps.

## Environment variables

Copy `.env.example` → `.env`. **Never commit `.env`.**

| Variable | Required | Purpose |
|----------|----------|---------|
| `ENV` | No | `development` (default) or `production` |
| `SECRET_KEY` | Prod yes | Session signing — app refuses weak keys when `ENV=production` |
| `PUBLIC_URL` | Yes for OAuth | Base URL for redirects; `https://` enables secure cookies |
| `GOOGLE_CLIENT_ID/SECRET` | Optional | Calendar OAuth |
| `GOOGLE_REDIRECT_URI` | Optional | Must match Google Console |
| `OPENROUTER_API_KEY` | Optional | AI holiday ideas + assistant |
| `OPENROUTER_DEFAULT_MODEL` | No | Default `openai/gpt-4o-mini` (allowlisted) |
| `TRUELAYER_*` | Optional | Open Banking |

**TrueLayer live mode:** set `TRUELAYER_ENV=production`, use live client secret, and set redirect URI to your public URL (e.g. Cloudflare tunnel). OAuth state is stored in DB (`banking_oauth_state` table) so tunnel callbacks work even if session started on localhost.

## Coding conventions (follow these)

1. **Minimize scope** — small focused diffs; match existing patterns.
2. **SQL** — always use `?` placeholders; never f-string SQL with user input.
3. **API routes** — protect with `Depends(require_user)` unless explicitly public (login, OAuth callbacks).
4. **Frontend** — prefer `esc()` for any user data in HTML; API client is `async function api(path, options)`.
5. **New integrations** — add `is_configured()` helper; return 503 when missing keys.
6. **Static cache bust** — bump `?v=N` on `index.html` script/style links **and** the `CACHE` constant in `sw.js` after JS/CSS changes (the service worker caches aggressively).
7. **No frontend build step** — do not add webpack/vite unless explicitly requested.
8. **Comments** — only for non-obvious business logic.

## AI Assistant architecture

`server/services/assistant.py`:

- Sends user message + household context JSON to OpenRouter with **tools** defined.
- Tool loop (max 8 rounds): model → `tool_calls` → `execute_tool()` → database CRUD → final reply.
- History stored per user in `settings` table key `assistant_history_{user_id}`.
- Tools: calendar events, tasks, appointments, holidays, bills, transactions, summaries.

To add a new tool:
1. Add tool schema to `TOOLS` list in `assistant.py`
2. Implement branch in `execute_tool()`
3. Add label in `TOOL_LABELS` in `app.js`
4. Test with `python -c "asyncio.run(assistant.chat(...))"`

## Security (already applied vs remaining)

**Applied:**
- Session cleared on login; OAuth state validation; security headers middleware
- Production mode disables `/docs`, reload, weak SECRET_KEY
- Vault downloads forced as attachment; MIME from extension
- OpenRouter model allowlist; CSV upload size cap
- `.env` gitignored
- Change-password flow (`POST /api/auth/change-password`); seed password env-driven (`FAMILY_PORTAL_SEED_PASSWORD` or random-logged)
- Login rate limiting (429 after repeated failures)
- OAuth/bank tokens encrypted at rest (Fernet key derived from `SECRET_KEY`)
- pytest suite in `tests/` — run with `python -m pytest`

**Still needed before internet exposure:**
- Escape all dynamic HTML in `app.js` (stored XSS)
- HTTPS at a reverse proxy for any new deployment
- Restrict AWS security group CIDRs

## Common AI tasks

| Task | Where to look |
|------|---------------|
| Add API endpoint | `server/api/routes.py` + `shared/schemas.py` + `database.py` |
| Add UI tab/section | `index.html` panel + `app.js` render function + `switchTab()` |
| Add DB table/column | `database.py` `_migrate()` + CRUD functions |
| Wire new integration | New file in `services/`, env vars in `.env.example`, status in `/api/integrations` |
| Fix bank OAuth | `open_banking.py`, `routes.py` banking callback, TrueLayer console redirect URI |
| Extend AI tools | `assistant.py` TOOLS + execute_tool |

## Testing manually

```bash
# Server health
python -m server.main

# Assistant smoke test (requires OPENROUTER_API_KEY in .env)
python -c "
import asyncio
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path('.env'))
from server.services import assistant
async def t():
    u = {'id':'luke','name':'Luke'}
    r = await assistant.chat(u, 'List open tasks')
    print(r['reply'])
asyncio.run(t())
"

# Login via curl (session cookie) — seeded accounts are lbillyard@gmail.com and
# lebillyard@gmail.com; fresh-DB password = FAMILY_PORTAL_SEED_PASSWORD (or the
# auto-generated one logged at seed time)
curl -c cookies.txt -X POST http://localhost:8090/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"lbillyard@gmail.com","password":"YOUR_SEED_PASSWORD"}'
```

Automated tests: pytest suite in `tests/` (isolated DB via `FAMILY_PORTAL_DB`) — run with `python -m pytest`.

## Deploy

See **docs/DEPLOY.md**. Production checklist:

```env
ENV=production
SECRET_KEY=<64-char hex from secrets.token_hex(32)>
PUBLIC_URL=https://your-domain.com
```

Use `deploy/family-portal.service` (uvicorn on 0.0.0.0:8090) behind Caddy/nginx/Cloudflare with TLS.

**Every deploy to the live box:**

1. The box is **NOT a git repo** — deploy = `scp` changed files to `/opt/family-portal` + `sudo systemctl restart family-portal`.
2. Frontend changed? Bump the `?v=` cache-bust in `server/static/index.html` **and** the `CACHE` constant in `server/static/sw.js`, or the service worker keeps serving stale assets.
3. Three timers run alongside the service: `family-portal-digest.timer` (07:00), `family-portal-sync.timer` (hourly), `family-portal-task-reminders.timer` (every 15 min) — unit files in `deploy/`; if you change one, copy it to `/etc/systemd/system/` and `daemon-reload`.

## Git / secrets policy

- **Never commit:** `.env`, `data/`, `*.db`, `cookies.txt`, uploaded documents
- **Always update:** `.env.example` when adding new env vars
- **Commit messages:** focus on why, not just what

## Questions agents should ask the user

- Is this for local dev only or public deploy?
- Which integrations are configured (Google, TrueLayer live vs sandbox, OpenRouter)?
- Should new features be household-shared or per-user?

---

*Last updated: July 2026 — includes AI assistant, document vault, Open Banking, security hardening pass.*
