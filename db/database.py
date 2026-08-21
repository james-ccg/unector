"""
Central place for the DB connection. Engine and Session are created here,
every other file imports from here.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import DATABASE_URL


class Base(DeclarativeBase):
    pass


# SQLite needs check_same_thread=False since aiogram is async and may use it
# from different threads. Not needed once we move to Postgres.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db():
    """Creates tables if they don't exist yet. Called on startup by BOTH
    bot.py and miniapp/api.py - two separate processes. On a completely
    fresh database, it's possible for both to see "no tables yet" at the
    same moment and race to create them (create_all's checkfirst does a
    plain SELECT then CREATE TABLE, not an atomic CREATE TABLE IF NOT
    EXISTS) - the loser's CREATE TABLE fails with an "already exists"
    error, which isn't a real problem (the tables ARE there now, just
    created by the other process), so it's swallowed here rather than
    crashing that process's startup."""
    from db import models  # noqa: F401 - import needed so models get registered
    from sqlalchemy.exc import OperationalError, ProgrammingError
    try:
        Base.metadata.create_all(engine)
    except (OperationalError, ProgrammingError) as e:
        if "already exists" not in str(e).lower():
            raise


def get_session():
    """Opens a new session per request (use with `with`)."""
    return SessionLocal()
