"""End-to-end run against a real server over real HTTP.

The pytest suite drives the app in-process through Starlette's TestClient,
which never opens a socket: no uvicorn, no real cookie jar, no HTTP parsing,
no middleware ordering as it actually ships. This starts the server the way
production does and talks to it over the network, so anything that only
breaks outside the test harness has somewhere to show up.

It brings its own database on a temporary file and its own port, so it never
touches freight_pilot.db or a server you already have running.

    python scripts/e2e.py            # run it
    python scripts/e2e.py --keep     # leave the temp server up afterwards

Exit code is the number of failed steps.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import time

import httpx
import pyotp

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = 8099
BASE = f"http://127.0.0.1:{PORT}"

PASSWORD = "correct-horse-battery-staple-9"

passed: list[str] = []
failed: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    if condition:
        passed.append(name)
        print(f"  ok    {name}")
    else:
        failed.append((name, detail))
        print(f"  FAIL  {name}")
        if detail:
            print(f"        {detail}")
    return condition


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def start_server(db_path: pathlib.Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    # Turnstile calls out to Cloudflare on register/login. A live external
    # dependency would make this run fail for reasons that are not the
    # app's, so it is off for the duration.
    env["TURNSTILE_SECRET_KEY"] = ""
    env["TURNSTILE_SITE_KEY"] = ""
    env["ENVIRONMENT"] = "development"

    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = pathlib.Path(sys.executable)

    return subprocess.Popen(
        [str(python), "-m", "uvicorn", "miniapp.api:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


def wait_for_server(timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(f"{BASE}/api/public/config", timeout=2)
            return True
        except httpx.HTTPError:
            time.sleep(0.4)
    return False


def csrf(client: httpx.Client) -> dict:
    """The header a mutating request has to carry alongside the cookie."""
    for name in ("__Host-fp_csrf", "fp_csrf"):
        token = client.cookies.get(name)
        if token:
            return {"X-CSRF-Token": token}
    return {}


def register(client: httpx.Client, mc: str, name: str = "E2E Freight") -> httpx.Response:
    return client.post("/api/auth/register", json={
        "mc_number": mc,
        "company_name": name,
        "email": f"owner{mc}@e2e.example",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
    })


def run() -> None:
    mc_a = "770001"
    mc_b = "770002"

    # ---------------------------------------------------------------
    section("1. The server is up and serving")
    r = httpx.get(f"{BASE}/api/public/config", timeout=10)
    check("public config responds", r.status_code == 200, f"got {r.status_code}")
    check("config names the turnstile key field", "turnstile_site_key" in r.json(), r.text[:120])

    for header, expected in [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
    ]:
        check(f"security header {header}", r.headers.get(header) == expected, r.headers.get(header, "(absent)"))
    csp = r.headers.get("Content-Security-Policy", "")
    check("CSP locks frame-ancestors", "frame-ancestors 'none'" in csp, csp[:80])
    check("CSP locks object-src", "object-src 'none'" in csp, csp[:80])

    # ---------------------------------------------------------------
    section("2. An unknown API path is a 404, not the SPA")
    r = httpx.get(f"{BASE}/api/definitely-not-real", timeout=10)
    check("status is 404", r.status_code == 404, f"got {r.status_code}")
    check("body is JSON, not HTML", r.headers.get("content-type", "").startswith("application/json"),
          r.headers.get("content-type", ""))

    # ---------------------------------------------------------------
    section("3. Registration and session")
    a = httpx.Client(base_url=BASE, timeout=20)
    r = register(a, mc_a)
    check("register succeeds", r.status_code == 200, r.text[:200])
    check("session cookie is set", any("fp_session" in c for c in a.cookies.keys()),
          str(list(a.cookies.keys())))
    check("csrf cookie is set", bool(csrf(a)), str(list(a.cookies.keys())))

    r = a.get("/api/me")
    check("session works", r.status_code == 200, r.text[:200])
    check("role is owner", r.json().get("role") == "owner", r.text[:200])
    company_a = r.json().get("company_id")

    # ---------------------------------------------------------------
    section("4. CSRF is required, and bound to this session")
    r = a.put("/api/me/status", json={"emoji": None, "text": "rolling", "expires_at": None})
    check("no CSRF header is refused", r.status_code == 403, f"got {r.status_code}")

    r = a.put("/api/me/status", json={"emoji": None, "text": "rolling", "expires_at": None},
              headers={"X-CSRF-Token": "not-a-real-token.0123456789abcdef"})
    check("a forged CSRF token is refused", r.status_code == 403, f"got {r.status_code}")

    r = a.put("/api/me/status", json={"emoji": None, "text": "rolling", "expires_at": None},
              headers=csrf(a))
    check("the real CSRF token works", r.status_code == 200, r.text[:200])

    # ---------------------------------------------------------------
    section("5. Two-factor authentication")
    r = a.post("/api/2fa/totp/setup", headers=csrf(a))
    check("totp setup returns a secret", r.status_code == 200 and "secret" in r.json(), r.text[:200])
    totp = pyotp.TOTP(r.json()["secret"])

    r = a.post("/api/2fa/totp/verify", json={"channel": "totp", "code": totp.now()}, headers=csrf(a))
    check("totp verifies and enables", r.status_code == 200, r.text[:200])

    r = a.post("/api/auth/logout", headers=csrf(a))
    check("logout succeeds", r.status_code == 200, r.text[:200])
    a.cookies.clear()

    r = a.post("/api/auth/owner", json={"mc_number": mc_a, "password": PASSWORD})
    body = r.json()
    check("password alone now demands a second factor", body.get("requires_2fa") is True, r.text[:200])
    pending = body.get("pending_token", "")

    # The vulnerability this session closed: the handshake token is handed
    # to the caller before any second factor, and used to be accepted as a
    # session cookie outright.
    attacker = httpx.Client(base_url=BASE, timeout=20)
    attacker.cookies.set("fp_session", pending)
    r = attacker.get("/api/me")
    check("the 2FA handshake token is NOT a session", r.status_code == 401,
          f"got {r.status_code} - 2FA can be skipped")
    attacker.close()

    # The code used to enable TOTP a moment ago has been consumed - the
    # server records its step and refuses it again, which is the replay
    # protection working. Wait for the next 30-second window.
    wait = 30 - (int(time.time()) % 30) + 1
    print(f"  ...    waiting {wait}s for the next TOTP window")
    time.sleep(wait)

    r = a.post("/api/2fa/login/verify", json={
        "pending_token": pending, "method": "totp", "code": totp.now(),
    })
    signed_in = check("completing the second factor signs in", r.status_code == 200, r.text[:200])
    check("session works after 2FA", a.get("/api/me").status_code == 200)
    if not signed_in:
        print("  ...    skipping the rest: nothing below can run signed out")
        return

    # ---------------------------------------------------------------
    section("6. Drivers, and the data behind the dashboard")
    r = a.post("/api/drivers", json={"full_name": "Dave Wheeler", "phone": "+15551234567"},
               headers=csrf(a))
    check("a driver can be added", r.status_code == 200, r.text[:200])
    driver_id = r.json().get("id") or r.json().get("driver_id")

    r = a.get("/api/drivers")
    check("the driver list loads", r.status_code == 200, r.text[:200])
    names = [d.get("full_name") for d in (r.json() if isinstance(r.json(), list) else r.json().get("drivers", []))]
    check("the new driver is in it", "Dave Wheeler" in names, str(names)[:200])

    r = a.post(f"/api/drivers/{driver_id}/link-token", headers=csrf(a))
    check("a linking code can be issued", r.status_code == 200, r.text[:200])

    # ---------------------------------------------------------------
    section("7. One company cannot read another's data")
    b = httpx.Client(base_url=BASE, timeout=20)
    r = register(b, mc_b, "Rival Freight")
    check("a second company registers", r.status_code == 200, r.text[:200])
    check("it is a different company", b.get("/api/me").json().get("company_id") != company_a)

    r = b.get(f"/api/drivers/{driver_id}")
    check("it cannot read the first company's driver", r.status_code == 403,
          f"got {r.status_code} - tenant isolation is broken")

    r = b.post(f"/api/drivers/{driver_id}/link-token", headers=csrf(b))
    check("it cannot issue a code for that driver", r.status_code in (403, 404),
          f"got {r.status_code}")
    b.close()

    # ---------------------------------------------------------------
    section("8. Limits hold")
    r = a.post("/api/auth/owner", content=b"x" * (3 * 1024 * 1024),
               headers={"Content-Type": "application/json"})
    check("an oversized body is refused", r.status_code == 413, f"got {r.status_code}")


    # ---------------------------------------------------------------
    section("9. Errors say which error, in the house style")
    r = httpx.post(f"{BASE}/api/auth/owner", json={"mc_number": "123456", "password": "wrong"}, timeout=10)
    detail = r.json().get("detail", "")
    check("a wrong password is 401", r.status_code == 401, f"got {r.status_code}")
    check("it does not say which half was wrong", "password" in detail.lower() and "mc" in detail.lower(),
          detail)
    banned = [w for w in ("invalid", "failed", "something went wrong", "sorry") if w in detail.lower()]
    check("it avoids the banned wording", not banned, f'"{detail}" contains {banned}')

    r = httpx.get(f"{BASE}/api/me", timeout=10)
    check("no session is 401", r.status_code == 401, f"got {r.status_code}")
    check("and says what to do", "log in" in r.json().get("detail", "").lower(),
          r.json().get("detail", ""))

    section("10. Rate limiting")
    # Last, deliberately: this exhausts the limiter for this address, so
    # anything checked after it would get a 429 instead of its real answer.
    burst = httpx.Client(base_url=BASE, timeout=20)
    codes = [burst.post("/api/auth/owner",
                        json={"mc_number": "999999", "password": "nope"}).status_code
             for _ in range(12)]
    burst.close()
    check("repeated bad logins get rate limited", 429 in codes, f"statuses: {codes}")

    a.close()


def main() -> int:
    keep = "--keep" in sys.argv
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="fp-e2e-")) / "e2e.db"

    print(f"database : {tmp}")
    print(f"server   : {BASE}")

    server = start_server(tmp)
    try:
        if not wait_for_server():
            print("\nThe server never came up. Nothing was tested.")
            return 1
        run()
    finally:
        if not keep:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    print()
    print("=" * 58)
    print(f"{len(passed)} passed, {len(failed)} failed")
    if failed:
        print()
        for name, detail in failed:
            print(f"  FAIL  {name}")
            if detail:
                print(f"        {detail}")
    print("=" * 58)
    return len(failed)


if __name__ == "__main__":
    raise SystemExit(main())
