# Freight Pilot

A Telegram dispatch bot for trucking companies: pulls Rate Confirmations from email, extracts
load details with AI, checks load pictures and BOLs, forwards PODs, tracks GPS proximity to
pickup/delivery, and gives owners a web dashboard (Mini App) to manage drivers and dispatchers.

## Stack

- **Bot** (`bot.py`) - aiogram 3, polls Telegram. The actual dispatch automation; runs as its
  own process, shares the database with the Mini App.
- **Backend** (`miniapp/api.py`) - FastAPI. JSON API for the dashboard, plus serves the built
  frontend as a single-origin SPA. Runs standalone with `uvicorn miniapp.api:app`.
- **Frontend** (`frontend/`) - React 19 + TypeScript + Vite. Builds to `frontend/dist/`, which
  the backend serves at `/` (if it hasn't been built yet, `/` shows a "run `npm run build`"
  notice instead of crashing).
- **AI** (`services/gemini_service.py`) - Google Gemini extracts structured data from RC PDFs
  and reviews load/BOL photos.

See [WEBSITE_STATUS.md](WEBSITE_STATUS.md) for the frontend's page map and auth model, and
[IMPROVEMENTS_SUMMARY.md](IMPROVEMENTS_SUMMARY.md) for a history of notable fixes.

## Prerequisites

- Python 3.12+
- Node 20+ (for the frontend)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- A [Gemini API key](https://aistudio.google.com/apikey) (free tier works)

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

### 2. Configure `.env`

Copy `.env.example` to `.env` and fill it in. At minimum you need `TELEGRAM_BOT_TOKEN` and
`GEMINI_API_KEY` to run the bot at all. Everything else (Gmail, Samsara, Stripe, 2FA channels,
Turnstile) is optional and the affected feature just replies "isn't set up yet" until
configured - nothing crashes with it missing.

Generate the encryption key used for stored credentials (Gmail refresh tokens, Samsara API
keys, etc.) once:

```bash
python config.py
```

Paste the printed value into `FERNET_MASTER_KEY` in `.env`.

### 3. Google OAuth client (for Gmail integration)

The dashboard's **Settings → Connect Gmail** button (the primary, supported way to connect an
inbox) does a server-side OAuth redirect, which requires a **Web application** OAuth client -
not "Desktop app". In [Google Cloud Console](https://console.cloud.google.com/) → APIs &
Services → Credentials → Create Credentials → OAuth client ID:

1. Application type: **Web application**.
2. Authorized redirect URI: the value of `GMAIL_OAUTH_REDIRECT_URI` in your `.env`
   (defaults to `http://localhost:8000/api/settings/gmail/callback` for local dev; set it to
   your real domain's equivalent path once deployed, and add that as a second authorized URI).
3. Put the resulting client ID/secret into `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

`gmail_setup.py` is a separate, optional CLI path for connecting Gmail without the dashboard
(`python gmail_setup.py --company-id 1`). It uses a local-loopback OAuth flow, which Google
only allows for a **Desktop app**-type client - it will not work with the Web application
client from above (different client, different redirect rules). If you want to use this
script, create a second OAuth client of type "Desktop app" and point `GOOGLE_CLIENT_ID`/
`GOOGLE_CLIENT_SECRET` at whichever one you're actually using at the time. Most setups can
ignore this script entirely and just use the dashboard button.

### 4. Database

A fresh database is created automatically (tables only, no data) the first time you run the
bot or the API - both call `init_db()` on startup. Nothing to do manually here.

The root-level `migrate_db*.py` scripts (`migrate_db.py`, `migrate_db_add_billing.py`, etc.)
are one-off, additive migrations for a database created *before* a given feature existed -
skip all of them on a brand-new database. Only run one if you're upgrading an existing
`freight_pilot.db` and a feature added after your last update isn't working.

### 5. Add a company and driver

Both are self-service from the dashboard now. Registering a company from `/register` is
Gmail-first: connect Gmail, confirm you own that inbox (a code or link emailed to it), then fill
in company details - nothing is created until that last step submits, so abandoning the flow
anywhere before then leaves nothing behind. Adding a driver is done from **Settings → Drivers**
once logged in as the owner - it creates the driver record and shows a one-time
`/linkdriver <code>` command. Add the bot to the driver's Telegram group and send that command
there to complete the link (no group ID needed - unlike `/setvehicle`, this doesn't require
`/myid` first).

`seed.py` still exists for quick local/test setup without going through the dashboard:

```bash
python seed.py --group-id -1001234567890 --mc 123456 --company "Axle Logistics" --driver-name "Jasur"
```

To find a group's ID for `seed.py`: add the bot to the driver+dispatch group and send `/myid` there.

### 6. Optional integrations

- **Samsara** (GPS proximity alerts) - connect from Settings in the dashboard, or
  `python samsara_setup.py --company-id 1 --api-key <token>`.
- **Stripe** (billing) - see `stripe_setup.py` and the `STRIPE_SECRET_KEY`/
  `STRIPE_WEBHOOK_SECRET` vars in `.env.example`.
- **Cloudflare Turnstile** (bot protection on register/login) - free, see the
  `TURNSTILE_SITE_KEY`/`TURNSTILE_SECRET_KEY` comment in `.env.example`. Login/register work
  normally, just unprotected, until both are set.
- **2FA channels** (email OTP via SMTP, SMS via Twilio, WebAuthn) - see the corresponding
  section of `.env.example`. TOTP and recovery codes need no external setup at all.

## Running it

```bash
# Bot (own process)
python bot.py

# API (own process) - serves the built frontend too, once you've run `npm run build`
uvicorn miniapp.api:app --reload

# Frontend dev server (hot reload; proxies API calls to the port above)
cd frontend && npm run dev
```

## Testing

```bash
pytest
```

Frontend type-checking/build: `cd frontend && npm run build`.
