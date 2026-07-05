# Family Portal

A household hub for calendar, finances, appointments, holidays, document vault, and an **AI assistant** — built for two adults with a navy + teal theme.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](requirements.txt)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)

## Features

| Tab | Capabilities |
|-----|--------------|
| **Home** | Dashboard, reminders, quick stats |
| **Calendar** | Events CRUD, Google Calendar sync |
| **Finances** | Bills, transactions, budgets, CSV import, **Open Banking** (Starling, Revolut, Amex, Virgin via TrueLayer) |
| **Appointments** | Medical, dental, vet bookings |
| **Holidays** | Trip planning, AI destination ideas (OpenRouter) |
| **Vault** | Upload & store insurance, passports, MOT docs, etc. |
| **AI Helper** | Chat assistant that can add events, tasks, holidays, bills — wired into the full system |
| **Settings** | Integrations, Google Calendar connect, bank connections |

Install as PWA: browser → “Add to Home Screen” (manifest + service worker included).

## Quick start

```bash
git clone https://github.com/lbillyard/family-portal.git
cd family-portal
python -m pip install -r requirements.txt
cp .env.example .env
python -m server.main
```

Open **http://localhost:8090**

On first run, SQLite seed data creates two household users. **Change default passwords before deploying publicly** (see `server/database.py` seed or add a change-password flow).

## Configuration

Copy `.env.example` to `.env` and fill in values. The app runs without optional keys — integrations show as unavailable until configured.

| Integration | Setup |
|-------------|-------|
| **Google Calendar** | [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → OAuth 2.0 → redirect `http://localhost:8090/api/auth/google/callback` |
| **OpenRouter AI** | [openrouter.ai/keys](https://openrouter.ai/keys) — powers holiday ideas + AI assistant |
| **TrueLayer Banking** | [console.truelayer.com](https://console.truelayer.com) → redirect `http://localhost:8090/api/banking/callback` (use sandbox first) |

For public OAuth callbacks (e.g. TrueLayer live), use a tunnel (Cloudflare) and set `PUBLIC_URL` + redirect URIs to match.

**Production:** set `ENV=production`, a strong `SECRET_KEY`, and `PUBLIC_URL=https://your-domain.com`.

## Documentation

| Doc | Purpose |
|-----|---------|
| **[AGENTS.md](AGENTS.md)** | **Start here for AI agents** — architecture, conventions, feature map, handoff |
| **[docs/BUILD.md](docs/BUILD.md)** | Detailed build notes, API reference, data model |
| **[docs/DEPLOY.md](docs/DEPLOY.md)** | AWS EC2 + Ubuntu deployment runbook |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | Planned work and known gaps |

## Stack

FastAPI · SQLite · vanilla JS · session auth · Google Calendar · TrueLayer Open Banking · OpenRouter · PWA

Port **8090** (local dev and deploy default).

## Deploy

Infrastructure scripts in `deploy/` are ready but not executed by default:

```powershell
# AWS (preview stack)
.\deploy\aws\deploy.ps1 -KeyName "your-key" -SkipUpload
```

Or Ubuntu: `sudo bash deploy/install-ubuntu.sh` after copying to `/opt/family-portal`.

See [docs/DEPLOY.md](docs/DEPLOY.md) for the full checklist.

## Security

- Never commit `.env` or `data/`
- Use HTTPS and strong secrets before exposing to the internet
- See [AGENTS.md](AGENTS.md) security section for applied vs remaining hardening

## License

Private household project — see repository owner for usage terms.
