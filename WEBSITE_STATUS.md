# Freight Pilot Website - Status

Supersedes the original plan for a separate hand-written static marketing
site (`miniapp/static/public/*` - HTML/CSS/JS, described in an earlier
version of this doc). That was never finished; every page it planned now
exists as a real page in the React app instead, alongside the dashboard.
There is no separate "public site" anymore - one app, one deploy.

## Stack

- **Frontend**: React 19 + TypeScript + Vite, in `frontend/`. Built to
  `frontend/dist/` and served by the FastAPI backend as a single-origin SPA
  (`miniapp/api.py` mounts it at `/`; if `frontend/dist` hasn't been built
  yet, `/` shows a "run `npm run build`" notice instead of crashing).
- **Backend**: FastAPI, `miniapp/api.py` - JSON API + serving the built
  frontend. Runs standalone with `uvicorn miniapp.api:app`.
- **Bot**: `bot.py` (aiogram) - the actual dispatch automation; separate
  process, shares the same database.

## Pages (`frontend/src/pages`, routed in `frontend/src/App.tsx`)

Public (no login):
- `/` - Home
- `/pages/pricing` - Pricing
- `/pages/faq` - FAQ
- `/pages/security` - Security
- `/pages/trust` - Trust/stats
- `/pages/updates` - Changelog
- `/login`, `/register`

Private (session cookie required, `PrivateRoute`):
- `/dashboard` - fleet overview: drivers, weekly/total gross, fleet status,
  driver detail modal (load history, subscription toggle for owners)
- `/settings` - company info, billing, Gmail/Samsara integration status,
  location alert rules, dispatcher logins, 2FA
- `/monitoring` - live GPS/load status per driver
- `/onboarding/connect-gmail` - mandatory first-run step for a new owner

`/dashboard` and `/monitoring` additionally require Gmail to be connected
(`RequireGmailConnected`) - the bot's core feature depends on it, so an
owner is routed to onboarding until that's done.

## Auth model

- Owner: MC# + password (registered via `/register`)
- Dispatcher: username + password, created by the owner from `/settings`
- Both support optional 2FA: TOTP, email/SMS/Telegram OTP, WebAuthn
  security keys, and recovery codes (`frontend/src/components/TwoFactorSettings.tsx`)

## Known gaps

- Footer social links (Twitter/LinkedIn) and Privacy Policy/Terms are
  placeholder "Coming soon" - no real profile URLs or legal copy exist yet
  to link to.
- `/pages/trust`'s public stats endpoint reports a fixed 99.9% uptime figure
  rather than a measured one - there's no uptime-monitoring system wired up.
