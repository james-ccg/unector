"""
Pytest session setup - points the app at a throwaway SQLite file instead of
the real freight_pilot.db, so running the test suite never creates or
touches real company/driver data. Must set DATABASE_URL before anything
else imports config.py or db/database.py (which build the engine at
import time), so this has to happen at conftest module scope.
"""
import os
import pathlib

_TEST_DB_PATH = pathlib.Path(__file__).parent / "test_freight_pilot.db"
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
