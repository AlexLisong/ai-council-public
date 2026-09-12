"""Accounts and sessions: scrypt password hashes, random bearer tokens stored hashed."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request

from . import db
from .config import ADMIN_PASSWORD, ADMIN_USERNAME, SESSION_DAYS

log = logging.getLogger("council.auth")

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD = 8


def validate_username(username: str) -> str:
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Username must be 3-32 characters: letters, digits, _ . -")
    return username


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD} characters")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()
    db.create_session(_hash_token(token), user_id, expires)
    return token


def revoke_token(token: str) -> None:
    db.delete_session(_hash_token(token))


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {"id": user["id"], "username": user["username"], "role": user["role"], "created_at": user["created_at"]}


def bootstrap_admin() -> None:
    """Create the master account on first start, then import any pre-auth JSON conversations to it."""
    db.init_db()
    db.purge_expired_sessions()
    admin = db.get_user_by_username(ADMIN_USERNAME)
    if admin is None:
        if not ADMIN_PASSWORD:
            raise RuntimeError("Set ADMIN_PASSWORD before creating the first administrator.")
        validate_password(ADMIN_PASSWORD)
        admin = db.create_user(ADMIN_USERNAME, hash_password(ADMIN_PASSWORD), role="admin")
        log.info("created administrator account")
    elif admin["role"] != "admin":
        log.warning("ADMIN_USERNAME %r exists but is not an admin; leaving it unchanged", ADMIN_USERNAME)
    db.import_legacy_json(admin["id"])


def _token_from_request(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


async def current_user(request: Request) -> dict[str, Any]:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")
    user = db.get_session_user(_hash_token(token))
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid; sign in again")
    request.state.token = token
    return user


async def current_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Master account required")
    return user


def can_access(user: dict[str, Any], conversation: dict[str, Any]) -> bool:
    return user["role"] == "admin" or conversation["owner_id"] == user["id"]
