"""
Password hashing (bcrypt) and login-session tokens (JWT) for the Mini App.
Kept separate from the Telegram bot's own logic - this module is only used
by miniapp/api.py.
"""
import time

import bcrypt
import jwt

from config import JWT_SECRET_KEY

ALGORITHM = "HS256"
TOKEN_LIFETIME_SECONDS = 60 * 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def create_token(payload: dict) -> str:
    data = dict(payload)
    data["exp"] = int(time.time()) + TOKEN_LIFETIME_SECONDS
    return jwt.encode(data, JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
