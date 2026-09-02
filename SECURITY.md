# Security

## Reporting a vulnerability

Email **security@freightpilot.example** with the details.

> Replace that address before publishing this file - it is a placeholder.
> A dedicated alias is worth setting up rather than a personal inbox: this
> repository is public, so whatever goes here is scraped. GitHub's private
> vulnerability reporting (Settings -> Code security -> Private reporting)
> is a good alternative that needs no address at all.

Please do not open a public issue for a security problem - a public report
is a disclosure, and it is readable by everyone before there is a fix.

Useful things to include: what you did, what happened, and what you expected
instead. A proof of concept helps enormously and does not need to be
polished. If you are unsure whether something counts, report it anyway.

You will get an acknowledgement within a few days. Freight Pilot is a small
project without a bounty programme, but credit is offered on any fix that
comes from a report, if you want it.

Please do not run automated scanners against a live deployment, and do not
access, modify or retain data belonging to anyone else while investigating.

## What is in place

Stated so anyone reviewing knows what to expect, and so a regression is
noticeable.

**Authentication.** Passwords are hashed with bcrypt. Sessions are JWTs
carried in an httpOnly cookie, so no script can read one, and every token
this app signs carries a `purpose` claim that is checked where it is spent -
a token minted for the 2FA handshake or an OAuth `state` is not a login
session. Optional second factors: TOTP, email/SMS/Telegram OTP, WebAuthn
security keys, and recovery codes. Auth and OTP endpoints are rate limited,
and register/login sit behind Cloudflare Turnstile.

**Authorisation.** Every endpoint that takes a resource id resolves it
against the caller's own company or account. Cross-tenant access is covered
by tests rather than convention.

**Data.** Stored third-party credentials - Gmail refresh tokens, Samsara API
keys, TOTP secrets, 2FA contact details - are encrypted at rest with Fernet.
API responses are shaped by explicit response models rather than returning
whole ORM rows.

**Requests.** State-changing requests need a CSRF token that is an HMAC over
the session, so matching halves alone do not pass. Bodies are size-limited.
All database access goes through the ORM; there is no string-built SQL
anywhere in the codebase. Uploads through the bot are restricted by MIME
type and size.

**Transport and headers.** HSTS, a restrictive Content-Security-Policy,
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, a referrer
policy, and a permissions policy. HTTPS redirection is available behind
`FORCE_HTTPS`, and session cookies take the `__Host-` prefix in production.

**Supply chain.** Dependency updates arrive weekly; CI runs the test suite,
`pip-audit`, `npm audit` and a gitleaks history scan on every push and again
on a weekly schedule.

## Deploying safely

`ENVIRONMENT=production` makes the app refuse to start on weak or missing
secrets - do not work around that. Set `FORCE_HTTPS=true` behind TLS, and
`TRUST_PROXY_HEADERS=true` only when a proxy you control terminates
connections in front of the app, since the header it enables is forgeable by
anyone if nothing trustworthy is setting it.
