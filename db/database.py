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
    """Creates tables if they don't exist yet. Called on bot startup."""
    from db import models  # noqa: F401 - import needed so models get registered
    Base.metadata.create_all(engine)


def get_session():
    """Opens a new session per request (use with `with`)."""
    return SessionLocal()
