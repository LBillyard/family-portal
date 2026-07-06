# WhatsApp via Twilio — production sender setup

Switching WhatsApp from the free Meta Cloud API number to a Twilio-registered
WhatsApp sender. The application code is already complete and defaults to the
Twilio provider (`WHATSAPP_PROVIDER=twilio`); this is a **config + Twilio-console**
task only.

> URLs contain a Twilio region segment (usually `us1`). If a link 404s, go to
> https://console.twilio.com and use the top search bar with the term in **[brackets]**.

## Step 0 — Reality check
WhatsApp always requires a Meta/Facebook business account. Registering a sender
through Twilio routes through that same Meta gate — it does not skip it, it just
wraps it in a smoother flow. Steps needing you personally: Facebook login,
OAuth consent, and Meta business verification.

## Step 1 — Credentials
https://console.twilio.com — dashboard **Account Info** panel:
- **Account SID** (`AC…`) → `.env` `TWILIO_ACCOUNT_SID`
- **Auth Token** → `.env` `TWILIO_AUTH_TOKEN`

## Step 2 — Confirm the number
https://console.twilio.com/us1/develop/phone-numbers/manage/incoming  **[Active numbers]**
- Must be a mobile/local number (toll-free/short codes generally not supported).
- Must NOT already be registered on WhatsApp anywhere (incl. the current free Meta setup).

## Step 3 — Create the WhatsApp sender
https://console.twilio.com/us1/develop/sms/senders/whatsapp-senders  **[WhatsApp senders]**
- Click **Create new sender** → launches Meta **Embedded Signup** popup.
- **You:** log into Facebook, create/select a **Meta Business Manager** account, grant Twilio consent.

## Step 4 — Business profile + verification
- Select the Twilio number as the sender.
- Set **Display name** (Meta-reviewed) + category; complete number OTP.
- **Meta business verification** may run — hours to ~2 days, on Meta's side.
  Unverified accounts still get a limited tier (a few recipients), enough for family use.
- When approved → sender shows Online/Approved. Number → `.env`
  `TWILIO_WHATSAPP_FROM=whatsapp:+<number>`.

## Step 5 — Digest content template (for the proactive 7am send)
https://console.twilio.com/us1/develop/sms/content-template-builder  **[Content Template Builder]**
- **Create new** → Type: Text · Category: Utility · Language: English (UK)
- Body has ONE variable `{{1}}` (the app passes the whole digest as `{{1}}` —
  see `server/services/whatsapp_twilio.py` `send_digest`). If a bare `{{1}}` is
  rejected, wrap it: `Good morning! Here's your family digest:\n\n{{1}}`
- Submit for WhatsApp approval → copy **Content SID** (`HX…`) → `.env` `TWILIO_CONTENT_SID`.
- Until approved, code falls back to free-form (only reaches people who messaged
  within 24h). Replies work immediately; the 7am proactive digest needs this template.

## Step 6 — Inbound webhook
On the sender's config set the **incoming message webhook** (POST) to:
```
https://<your-public-domain>/api/whatsapp/twilio
```
Must match `PUBLIC_URL` in `.env` (signature is validated in
`server/api/routes.py` `whatsapp_twilio_receive`).

## Step 7 — Config & test
1. Fill `.env`: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`,
   `TWILIO_CONTENT_SID`, `WHATSAPP_PROVIDER=twilio`.
2. Set the SAME values on the live AWS box (16.60.165.35:8090) — the 7am digest
   cron runs there.
3. Restart the app.
4. Logged in, POST `/api/whatsapp/test-digest` to send a real digest to yourself.

## Env var reference
| Var | Value | Source |
|-----|-------|--------|
| `WHATSAPP_PROVIDER` | `twilio` | fixed |
| `TWILIO_ACCOUNT_SID` | `AC…` | console dashboard |
| `TWILIO_AUTH_TOKEN` | token | console dashboard |
| `TWILIO_WHATSAPP_FROM` | `whatsapp:+<num>` | approved sender |
| `TWILIO_CONTENT_SID` | `HX…` | Content Template Builder |
| `TWILIO_VALIDATE` | `true` (set `false` only during first setup) | — |
