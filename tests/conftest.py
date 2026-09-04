"""
Pytest session setup - points the app at a throwaway SQLite file instead of
the real unector.db, so running the test suite never creates or
touches real company/driver data. Must set DATABASE_URL before anything
else imports config.py or db/database.py (which build the engine at
import time), so this has to happen at conftest module scope.
"""
import os
import pathlib

_TEST_DB_PATH = pathlib.Path(__file__).parent / "test_unector.db"
_TEST_DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

from db.database import init_db  # noqa: E402

init_db()


def pytest_sessionfinish(session, exitstatus):
    from db.database import engine

    engine.dispose()  # release SQLite's file handle before deleting (Windows locks it otherwise)
    try:
        _TEST_DB_PATH.unlink(missing_ok=True)
    except OSError:
        pass  # best-effort cleanup - a stray leftover test DB is harmless, it's gitignored


# ------------------------------------------------------------------
# Shared HTTP-test fixtures.
#
# These live here rather than in test_api.py because more than one module
# now drives the API (the game leaderboard has its own suite), and a fixture
# defined inside a test module is invisible to every other one.
# ------------------------------------------------------------------
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import miniapp.api as api_module  # noqa: E402
from miniapp.api import app  # noqa: E402
from miniapp.auth import CSRF_COOKIE_NAME  # noqa: E402


@pytest.fixture(autouse=True)
def _disable_turnstile(monkeypatch):
    """Register/login call out to Cloudflare's live siteverify endpoint
    whenever TURNSTILE_SECRET_KEY is set - which breaks these tests (no
    token to send) as soon as a real key is configured in .env. Tests
    shouldn't depend on a live external service or on what's in .env, so
    force it off here regardless of the environment's actual config."""
    monkeypatch.setattr(api_module, "TURNSTILE_SECRET_KEY", None)


@pytest.fixture
def client():
    # Rate-limit counters live on the shared `app.state.limiter`, not per
    # TestClient instance - without resetting, tests would trip each
    # other's limits since they all originate from the same test IP.
    app.state.limiter.reset()
    return TestClient(app)


def csrf_headers(client: TestClient) -> dict:
    """Reads the CSRF cookie the last login/register response set on this
    client and returns the header a mutating request must send alongside it."""
    token = client.cookies.get(CSRF_COOKIE_NAME)
    assert token, "no CSRF cookie set - must log in/register on this client first"
    return {"X-CSRF-Token": token}


# Hand-picked MC numbers have now collided three separate times as suites
# grew, each time as a confusing "already registered" failure that only
# appears in a full run. A counter can't collide, and the leading zero keeps
# it clear of every hardcoded six-digit number in the existing tests (they
# all start non-zero).
import itertools  # noqa: E402

_mc_counter = itertools.count(1)


def unique_mc() -> str:
    """A six-digit MC number no other test in this run will use."""
    return f"0{next(_mc_counter):05d}"
