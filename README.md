# Freight Pilot

A Telegram dispatch bot for trucking companies: pulls Rate Confirmations from email, extracts
load details with AI, checks load pictures and BOLs, forwards PODs, tracks GPS proximity to
pickup/delivery, and gives owners a web dashboard (Mini App) to manage drivers and dispatchers.

## Status

Freight Pilot is new. The first commit is dated 19 August 2026, and the whole history is
visible in `git log` - there is no earlier version. Everything described below works, but read
this before assuming it is a finished product:

- **Not deployed anywhere permanent.** It runs locally. `MINIAPP_URL` currently points at a
  tunnel, so the dashboard links the bot hands out change whenever that tunnel restarts. A real
  domain is the next infrastructure job.
- **The Google OAuth consent screen is unpublished**, which means Google revokes each Gmail
  refresh token after exactly 7 days. The dashboard warns two days ahead and offers a reconnect,
  and the countdown disappears on its own once the screen is published - see
  `GOOGLE_OAUTH_TESTING_MODE` in `.env.example`.
- **The Privacy Policy and Terms pages are real, but have not been reviewed by a lawyer.**
- **The public stats on `/pages/trust` are read live from the database**, so they show whatever
  is actually there - which on a fresh install is zeros.

`pytest` currently runs 423 tests, all passing.

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

See [WEBSITE_STATUS.md](WEBSITE_STATUS.md) for the frontend's page map, auth model and known
gaps. [IMPROVEMENTS_SUMMARY.md](IMPROVEMENTS_SUMMARY.md) is a one-off write-up of the `/bol`,
`/loadpics` and `/dashboard` response rewrite from 20 August 2026 - it is not kept up to date,
and `git log` is the actual history.

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

Once the group is linked, the bot reads its description. Carriers keep one group per truck and
write the unit number, trailer, driver and phone numbers there, so the bot extracts those and
posts them back with **Confirm** and **Not now**. The same reading appears in **Settings →
Drivers** with every value editable; confirming from either side saves it, and whichever side is
second is told it is already done. Nothing reaches the driver or truck record until someone
confirms - a group description is a note a dispatcher typed, not a source of record, so anything
that disagrees with what is on file is shown rather than applied.

Send `/readbio` in the group to read the description again after editing it. The **Details**
button on any driver in Settings opens the same fields for typing in by hand, which is the path
for carriers who keep nothing in the description.

`seed.py` still exists for quick local/test setup without going through the dashboard:

```bash
python seed.py --group-id -1001234567890 --mc 123456 --company "Test Carrier LLC" --driver-name "Test Driver"
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

The bot process also runs two background jobs: the GPS location monitor, and an hourly pass
that emails owners two days before their trial ends. Both live inside `bot.py`, so nothing is
sent while only the API is running - worth knowing before wondering where a reminder went.

## Notifications

Three channels: the bell in the dashboard, a Telegram DM, and email. `services/notification_events.py`
is the catalogue - what the app can tell somebody, who it is for, and where it goes when nobody has
said otherwise - and everything else reads from it, so the preference screen, the delivery service
and the tests cannot drift apart.

`notification_service.notify(company_id, event_key, title=..., body=..., link=...)` is the only
entry point. It works out who at the company wants it and where, tries each channel independently,
and logs and swallows every failure: a load was dispatched whether or not the email went out, and
an SMTP timeout rolling back a dispatch would be far worse than a missed message. Call
`notify_async` from the bot, which is async and would otherwise stall its event loop on SMTP.

Two things cannot be switched off, and the settings screen shows them locked rather than hiding
them. The dashboard list always fires - email can bounce and Telegram refuses to let a bot message
anyone who has not started a chat with it first, so the bell is the one channel that always arrives
and therefore the record of what was sent. And events with a real consequence attached - a failed
payment, a sign-in nobody recognises, an integration that quietly stopped working - ignore
preferences entirely, because whoever muted one a year ago will not remember doing so on the day it
matters.

Preferences are stored only where they differ from the default. Writing a full grid of switches when
an account is created would freeze today's defaults for everyone who never opens the page, and an
event added later would reach nobody.

Note that GPS proximity alerts and load dispatches to the driver's own group are a separate thing -
see `LocationAlertRule` and bot.py. That is dispatch doing its job, not a notification anyone should
be able to mute.

## Link previews

The card Telegram, X and WhatsApp show when someone pastes a link comes from Open Graph tags in
`frontend/index.html`. Those crawlers do not run JavaScript, so nothing React renders can reach
them - the tags have to be in the HTML the server sends.

`og:image` and `og:url` are written relative there and rewritten to absolute per request by
`serve_react_app` in `miniapp/api.py`, against whatever host the request arrived on. A relative
`og:image` is never fetched, and a hardcoded absolute one goes stale every time a dev tunnel
restarts, so neither alternative works.

Two details are easy to lose and invisible until a link is shared. `og:site_name` is what stops
the card naming the host instead of the product - without it a tunnel made it read
"Trycloudflare". And `twitter:card` set to `summary_large_image` is what chooses a large image
over a small square thumbnail; Telegram honours it, and without it the picture is a thumbnail
however big the file is.

The image itself is built rather than exported by hand, so it stays in step with the logo and
the brand colours:

```bash
python scripts/make_og_image.py
```

It writes `frontend/public/og-image.png` at 1200x630, the size every platform documents. The
script needs DM Sans, which is a build input rather than something committed - run it once and
it prints how to fetch it.

Telegram caches a preview per URL and will keep showing an old one. Send the link to
[@WebpageBot](https://t.me/WebpageBot) to make it re-read the page.


### Icons

`favicon.svg` is the one that matters: sharp at every size, and it flips between a dark and a
light mark through a `prefers-color-scheme` rule inside the file, which no raster format can do.
Roughly 95% of browsers use it. Safari ignores it and falls back to `favicon.ico`, and iOS wants
an `apple-touch-icon` for the home screen - so the three raster files are what stop that share of
visitors seeing no icon at all.

```bash
python scripts/make_icons.py
```

They are drawn on the brand's dark tile rather than left transparent. iOS fills transparency in a
touch icon with black, and a raster icon cannot follow the browser theme the way the SVG does, so
a transparent dark mark would vanish on a dark tab bar. Corners stay square because iOS and
Android round them themselves.

`manifest.webmanifest` makes the site installable - an icon on the home screen that opens without
browser chrome. Its icons are separate files from the ones above: Android may crop a maskable icon
to any shape and only promises to keep a circle of radius 40% of the width, so that one is padded
to fit. The mark is landscape, and at the ordinary inset its corners fall outside that circle. It
is a separate file rather than the same one declared `"any maskable"`, because that combination
makes a browser use the padded version everywhere, and padding meant for a crop looks like a
mistake when nothing is cropping it.

## Testing

```bash
pytest
```

Frontend type-checking/build: `cd frontend && npm run build`.

`pytest` drives the app in-process, which never opens a socket. For a run
against a real uvicorn over real HTTP - registration, 2FA, tenant isolation,
CSRF, rate limits, the error copy - there is an end-to-end script. It starts
its own server on port 8099 with a throwaway database, so it touches neither
`freight_pilot.db` nor anything you already have running:

```bash
python scripts/e2e.py
```

The game's physics has no assertions a type checker or a screenshot could
catch, so it has a measurement harness of its own - stillness, load balance,
acceleration, impacts, recovery, wrecks and hazards:

```bash
cd frontend && npm run physics
```
