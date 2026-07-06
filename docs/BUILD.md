# Family Portal — Build Documentation

This document describes what was built across all phases, how the pieces fit together, and how to run the app locally.

## Overview

Family Portal is a household hub for two adults: calendar, finances, appointments, holidays, tasks, and a document vault. The UI uses the same **navy + teal** palette as the Pokemon scraper project.

| Layer | Technology |
|-------|------------|
| Backend | FastAPI (Python 3.11+) |
| Frontend | Vanilla HTML / CSS / JS (no build step) |
| Database | SQLite (`data/family.db`) |
| Auth | Session cookies + PBKDF2 password hashing (stdlib) |
| Calendar sync | Google Calendar OAuth 2.0 |
| AI | OpenRouter API (holiday ideas) |
| PWA | Web manifest + service worker (offline shell) |

---

## Project structure

```
The Family Portal/
├── server/
│   ├── main.py                 # FastAPI app, sessions, static files
│   ├── database.py             # SQLite schema, CRUD, seed data
│   ├── auth.py                 # Login / password verification
│   ├── api/routes.py           # REST endpoints
│   ├── services/
│   │   ├── dashboard.py        # Home tab aggregates
│   │   ├── google_calendar.py  # OAuth + two-way sync
│   │   ├── openrouter.py       # AI holiday suggestions + model allowlist
│   │   ├── assistant.py        # AI chat + OpenRouter tool calling
│   │   ├── open_banking.py     # TrueLayer Open Banking
│   │   ├── documents.py        # Vault file storage helpers
│   │   └── csv_import.py       # Bank CSV parsing
│   └── static/
│       ├── index.html          # Single-page UI
│       ├── app.js              # Tab rendering + API client
│       ├── style.css           # Theme + components
│       ├── manifest.json       # PWA manifest
│       ├── sw.js               # Service worker (static cache)
│       ├── icon-192.png
│       └── icon-512.png
├── shared/schemas.py           # Pydantic request/response models
├── deploy/                     # AWS + systemd (ready, not executed)
├── docs/
│   ├── BUILD.md                # This file
│   ├── DEPLOY.md               # Deployment runbook
│   └── ROADMAP.md              # Planned work & gaps
├── AGENTS.md                   # AI agent handoff (read first for continuation)
├── scripts/generate_icons.py   # Regenerate PWA icons
├── data/family.db              # Created on first run (gitignored)
├── requirements.txt
└── .env.example
```

---

## Phases

### Phase 1 — Core app (complete)

- SQLite schema with seed users, bills, events, appointments, trips, budgets
- Session-based login (`lbillyard@gmail.com` / `lebillyard@gmail.com`; fresh-DB seed password comes from `FAMILY_PORTAL_SEED_PASSWORD`, or is auto-generated and logged once at seed time)
- Full CRUD via `/api/*` for events, bills, transactions, tasks, appointments, trips, documents
- Dashboard built from live queries (not mock data)
- Modal forms wired to POST endpoints

### Phase 2 — Integrations (complete)

| Feature | Endpoint / action | Config |
|---------|-------------------|--------|
| Google Calendar OAuth | `GET /api/auth/google/start` → callback → sync | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` |
| Manual calendar sync | `POST /api/calendar/sync` | Same as above |
| CSV bank import | `POST /api/finances/import-csv` | None (upload `.csv` from Finances tab) |
| **Open Banking sync** | `GET /api/banking/connect/{provider}` → callback → sync | `TRUELAYER_CLIENT_ID`, `TRUELAYER_CLIENT_SECRET`, `TRUELAYER_REDIRECT_URI` |
| Sync all banks | `POST /api/banking/sync` | Same as above |
| List connections | `GET /api/banking/connections` | — |
| AI holiday ideas | `POST /api/holidays/ideas/generate` | `OPENROUTER_API_KEY`, optional `OPENROUTER_DEFAULT_MODEL` |
| **AI assistant** | `POST /api/assistant/chat` | `OPENROUTER_API_KEY` — tool calling for calendar, tasks, holidays, bills |
| **Document vault** | `POST /api/documents/upload`, `GET /api/documents/{id}/file` | Files in `data/uploads/` |
| Integration status | `GET /api/integrations` | — |

**CSV format** (flexible headers): expects columns like `date`, `description`/`narrative`, `amount`, optional `category`. Negative amounts = spending; positive = income. See `server/services/csv_import.py`.

**Google sync** pulls primary calendar events into `events` table with `source=google`. Portal-created events stay local until extended two-way sync is added.

**Open Banking** connects your household accounts via [TrueLayer](https://truelayer.com) (UK regulated aggregator):

| Provider | Type | Notes |
|----------|------|-------|
| Starling Bank | Current account | Full balance + 88 days transactions |
| Revolut | Current account | Same |
| American Express | Credit card | Connect main or supplementary card |
| Virgin Money | Credit card | 7-digit customer ID; select card at consent |

Each person connects their own accounts (Luke connects Amex, Partner connects Starling, etc.). Use **Sync all banks** on the Finances tab to refresh. UK consent expires after **90 days** — reconnect when prompted.

**Open Banking** replaces manual CSV for day-to-day use; CSV import remains as fallback.

### Phase 3 — PWA + deploy prep (complete, deploy not run)

- `manifest.json` + `sw.js` — caches static assets; API calls always go network-first
- `deploy/family-portal.service` — systemd unit for Ubuntu
- `deploy/install-ubuntu.sh` — venv, `.env` bootstrap, firewall, service start
- `deploy/aws/cloudformation.yaml` — single EC2 + optional Elastic IP (port **8090**)
- `deploy/aws/deploy.ps1` — CloudFormation + optional SCP upload

---

## Data model (SQLite)

| Table | Purpose |
|-------|---------|
| `users` | Household members, password hash, Google token JSON |
| `events` | Calendar (portal + Google) |
| `bills` | Recurring bills with pay action |
| `transactions` | Income/expense lines |
| `accounts` | Joint / personal accounts |
| `budgets` | Monthly category limits |
| `savings_goals` | Named savings targets |
| `tasks` | Home reminders |
| `appointments` | Medical, dental, etc. |
| `trips` | Planned holidays |
| `holiday_ideas` | AI-generated or saved ideas |
| `documents` | Vault metadata + file paths |
| `bank_connections` | TrueLayer OAuth tokens per user/provider |
| `banking_oauth_state` | Short-lived OAuth state for tunnel callbacks |
| `settings` | Key/value (e.g. `google_last_sync`, assistant chat history) |

Database file: `data/family.db` — delete to reset with fresh seed data.

---

## API reference (authenticated unless noted)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/login` | Login (public) |
| POST | `/api/auth/logout` | Clear session |
| GET | `/api/auth/me` | Current user |
| GET | `/api/dashboard` | Home tab payload |
| GET | `/api/calendar` | Users + events |
| POST | `/api/events` | Create event |
| POST | `/api/calendar/sync` | Sync all Google calendars |
| GET | `/api/finances` | Bills, transactions, summary |
| POST | `/api/bills` | Add bill |
| POST | `/api/bills/{id}/pay` | Mark paid |
| POST | `/api/transactions` | Add transaction |
| POST | `/api/finances/import-csv` | Upload CSV |
| GET | `/api/appointments` | List appointments |
| POST | `/api/appointments` | Create appointment |
| GET | `/api/holidays` | Trips + ideas |
| POST | `/api/holidays/trips` | Plan trip |
| POST | `/api/holidays/ideas/generate` | AI ideas |
| POST | `/api/holidays/ideas/{id}/toggle` | Save/unsave idea |
| GET/POST | `/api/tasks`, `/api/tasks/{id}` | Tasks |
| GET/POST/DELETE | `/api/documents`, upload, file download | Document vault |
| GET/POST | `/api/assistant/chat`, `/api/assistant/clear` | AI assistant |
| GET/POST | `/api/banking/*` | Open Banking connect/sync |
| GET | `/api/settings` | Settings tab |
| GET | `/api/integrations` | Feature flags |

Google OAuth routes redirect the browser; no JSON response.

---

## Environment variables

Copy `.env.example` → `.env`:

```env
ENV=development                        # production disables /docs, reload; requires strong SECRET_KEY
SECRET_KEY=long-random-string          # Required in production
PUBLIC_URL=http://localhost:8090       # Used in OAuth redirects; https:// enables secure cookies

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8090/api/auth/google/callback

OPENROUTER_API_KEY=
OPENROUTER_DEFAULT_MODEL=openai/gpt-4o-mini

TRUELAYER_CLIENT_ID=
TRUELAYER_CLIENT_SECRET=
TRUELAYER_REDIRECT_URI=http://localhost:8090/api/banking/callback
TRUELAYER_ENV=sandbox
```

Without Google/OpenRouter/TrueLayer keys, the app runs fully — integration buttons show as disabled in Settings, and connect actions return 503 with a clear message.

---

## Local development

```powershell
cd "C:\Users\Luke\Desktop\Cursor Projects\The Family Portal"
python -m pip install -r requirements.txt
python -m server.main
```

Open **http://localhost:8090**. Uvicorn runs with `--reload` on port **8090**.

Regenerate PWA icons:

```powershell
python scripts/generate_icons.py
```

---

## Security notes

- Change default passwords before any network exposure
- Set a strong `SECRET_KEY`; app refuses weak keys when `ENV=production`
- Security headers middleware, session rotation on login, vault downloads as attachment
- Restrict AWS security group CIDRs — defaults are open
- Google/bank tokens stored in SQLite (encrypt at rest for production)
- Session cookies: `https_only` when `PUBLIC_URL` is HTTPS or in production
- Full XSS hardening in frontend still pending — see `docs/ROADMAP.md`

---

## Future work

See **[docs/ROADMAP.md](ROADMAP.md)** for the prioritized backlog.
