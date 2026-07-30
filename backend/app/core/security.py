"""User-table authentication: bcrypt password hashing + JWT bearer tokens.

Chosen over a shared secret to keep a per-user audit trail (who queried what),
which matters because the underlying data contains student PII.
"""
from __future__ import annotations

import datetime as dt

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import appdb
from .config import settings

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    # bcrypt operates on the first 72 bytes; truncate explicitly to avoid errors.
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def create_user(username: str, password: str) -> None:
    appdb.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?) "
        "ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash",
        [username, hash_password(password)],
    )


def bootstrap_admin() -> None:
    row = appdb.query_one("SELECT COUNT(*) FROM users")
    if row and row[0] == 0:
        create_user(settings.bootstrap_admin_user, settings.bootstrap_admin_password)


def authenticate(username: str, password: str) -> bool:
    row = appdb.query_one("SELECT password_hash FROM users WHERE username = ?", [username])
    if not row:
        return False
    return verify_password(password, row[0])


def issue_token(username: str) -> str:
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": username, "exp": exp}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
        return payload["sub"]
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
