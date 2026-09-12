"""SQLite persistence: users, sessions, conversations.

One file at data/council.db. Conversations keep their message list as a JSON blob;
ownership, titles and timestamps are columns so listing and access checks are cheap.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from .config import DATA_DIR, DB_PATH, SQLITE_JOURNAL_MODE

log = logging.getLogger("council.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'council' CHECK (mode IN ('chat', 'council')),
    messages TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conversations_owner ON conversations(owner_id, created_at);
CREATE TABLE IF NOT EXISTS panels (
    id TEXT PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    definition TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS panels_owner ON panels(owner_id, updated_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute(f"PRAGMA journal_mode = {SQLITE_JOURNAL_MODE}")
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(conversations)")}
        if "mode" not in columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN mode TEXT NOT NULL DEFAULT 'council' CHECK (mode IN ('chat', 'council'))")


def mark_interrupted_assistant(message: dict[str, Any]) -> bool:
    """Normalize an assistant turn known to have no live worker, preserving its work."""
    if message.get("role") != "assistant":
        return False
    changed = False
    incomplete = message.get("final") is None
    if message.get("waiting_for_input") is not None or (incomplete and "waiting_for_input" not in message):
        message["waiting_for_input"] = None
        changed = True
    if incomplete and not message.get("error"):
        message["error"] = (
            "Chat interrupted: the server or connection stopped. Your partial response is saved."
            if message.get("mode") == "chat" else
            "Debate interrupted: the server or connection stopped. Saved rounds and human thoughts are available for a follow-up."
        )
        changed = True
    return changed


def recover_interrupted_runs() -> int:
    """At single-worker startup, no saved in-progress turn has a running controller."""
    recovered = 0
    with connect() as conn:
        rows = conn.execute("SELECT id, messages FROM conversations").fetchall()
        for row in rows:
            messages = json.loads(row["messages"])
            changed = False
            for message in messages:
                changed = mark_interrupted_assistant(message) or changed
            if changed:
                conn.execute(
                    "UPDATE conversations SET messages = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(messages, ensure_ascii=False), now_iso(), row["id"]),
                )
                recovered += 1
    if recovered:
        log.info("recovered interrupted state in %d conversation(s)", recovered)
    return recovered


def import_legacy_json(owner_id: int) -> int:
    """One-time import of pre-auth JSON conversations (data/conversations/*.json) for `owner_id`.

    Imported files are renamed to *.json.imported so the import never runs twice.
    """
    folder = Path(DATA_DIR)
    if not folder.exists():
        return 0
    count = 0
    with connect() as conn:
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT OR IGNORE INTO conversations (id, owner_id, created_at, updated_at, title, messages) VALUES (?, ?, ?, ?, ?, ?)",
                    (data["id"], owner_id, data.get("created_at", now_iso()), now_iso(), data.get("title", "New Conversation"), json.dumps(data.get("messages", []), ensure_ascii=False)),
                )
                path.rename(path.with_suffix(".json.imported"))
                count += 1
            except (OSError, ValueError, KeyError) as e:
                log.warning("skipping legacy file %s: %s", path.name, e)
    if count:
        log.info("imported %d legacy conversation(s) into the database for user id %d", count, owner_id)
    return count


# ---- users -------------------------------------------------------------------

def create_user(username: str, password_hash: str, role: str = "user") -> dict[str, Any]:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, role, now_iso()),
        )
        return get_user_by_id(cur.lastrowid, conn)


def get_user_by_id(user_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict[str, Any]]:
    if conn is not None:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def count_users() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def list_users() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT u.id, u.username, u.role, u.created_at, COUNT(c.id) AS conversation_count "
            "FROM users u LEFT JOIN conversations c ON c.owner_id = u.id GROUP BY u.id ORDER BY u.created_at"
        ).fetchall()
        return [dict(r) for r in rows]


# ---- sessions ----------------------------------------------------------------

def create_session(token_hash: str, user_id: int, expires_at: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now_iso(), expires_at),
        )


def get_session_user(token_hash: str) -> Optional[dict[str, Any]]:
    """Return the user for a live session, deleting the session if it has expired."""
    with connect() as conn:
        row = conn.execute(
            "SELECT s.expires_at, u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] < now_iso():
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            return None
        user = dict(row)
        user.pop("expires_at", None)
        return user


def delete_session(token_hash: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def purge_expired_sessions() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))


# ---- conversations -----------------------------------------------------------

def _row_to_conversation(row: sqlite3.Row, with_messages: bool = True) -> dict[str, Any]:
    conv = {
        "id": row["id"],
        "owner_id": row["owner_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "title": row["title"],
        "mode": row["mode"],
    }
    if "owner_username" in row.keys():
        conv["owner_username"] = row["owner_username"]
    if with_messages:
        conv["messages"] = json.loads(row["messages"])
    else:
        conv["message_count"] = row["message_count"]
    return conv


def create_conversation(conversation_id: str, owner_id: int, mode: str = "council") -> dict[str, Any]:
    if mode not in {"chat", "council"}:
        raise ValueError("Conversation mode must be chat or council")
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, owner_id, created_at, updated_at, title, mode, messages) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (conversation_id, owner_id, ts, ts, "New Conversation", mode, "[]"),
        )
    return {"id": conversation_id, "owner_id": owner_id, "created_at": ts, "updated_at": ts, "title": "New Conversation", "mode": mode, "messages": []}


def get_conversation(conversation_id: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            "SELECT c.*, u.username AS owner_username FROM conversations c JOIN users u ON u.id = c.owner_id WHERE c.id = ?",
            (conversation_id,),
        ).fetchone()
        return _row_to_conversation(row) if row else None


def list_conversations(owner_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Metadata for one owner's conversations, or for everyone when owner_id is None (admin)."""
    sql = (
        "SELECT c.id, c.owner_id, c.created_at, c.updated_at, c.title, c.mode, u.username AS owner_username, "
        "json_array_length(c.messages) AS message_count "
        "FROM conversations c JOIN users u ON u.id = c.owner_id"
    )
    params: tuple = ()
    if owner_id is not None:
        sql += " WHERE c.owner_id = ?"
        params = (owner_id,)
    sql += " ORDER BY c.created_at DESC"
    with connect() as conn:
        return [_row_to_conversation(r, with_messages=False) for r in conn.execute(sql, params).fetchall()]


def save_messages(conversation_id: str, messages: list[dict[str, Any]]) -> None:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE conversations SET messages = ?, updated_at = ? WHERE id = ?",
            (json.dumps(messages, ensure_ascii=False), now_iso(), conversation_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Conversation {conversation_id} not found")


def update_title(conversation_id: str, title: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (title, now_iso(), conversation_id))


def delete_conversation(conversation_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cur.rowcount > 0


# ---- personal panels ---------------------------------------------------------

def migrate_retired_models() -> int:
    """Rewrite saved personal panels that still point at explicitly retired provider/model pairs.

    Conservative by design: only denylisted pairs are touched, nothing is written unless the
    replacement is a configured model, a bad row is logged and skipped rather than failing
    startup, and `updated_at` is left alone so the user's panel ordering does not change.
    Idempotent; returns the number of panels changed.
    """
    from . import config  # runtime import so tests can patch config.PROVIDERS / load_council_config

    if not config.replacement_available():
        log.error("skipping retired-model migration: replacement model is not configured")
        return 0
    changed = 0
    with connect() as conn:
        rows = conn.execute("SELECT id, owner_id, definition FROM panels").fetchall()
        for row in rows:
            try:
                definition = json.loads(row["definition"])
                changes = config.retire_models(definition)
            except (ValueError, TypeError, AttributeError) as e:
                log.warning("panel %s: skipped by retired-model migration (%s)", row["id"], e)
                continue
            if not changes:
                continue
            conn.execute(
                "UPDATE panels SET definition = ? WHERE id = ?",
                (json.dumps(definition, ensure_ascii=False), row["id"]),
            )
            changed += 1
            log.info("panel %s (owner %s): %s", row["id"], row["owner_id"], "; ".join(changes))
    if changed:
        log.info("migrated %d saved panel(s) away from retired models", changed)
    return changed


def _row_to_panel(row: sqlite3.Row) -> dict[str, Any]:
    return {**dict(row), "definition": json.loads(row["definition"])}


def create_panel(panel_id: str, owner_id: int, definition: dict[str, Any]) -> dict[str, Any]:
    timestamp = now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT INTO panels (id, owner_id, created_at, updated_at, definition) VALUES (?, ?, ?, ?, ?)",
            (panel_id, owner_id, timestamp, timestamp, json.dumps(definition, ensure_ascii=False)),
        )
    return {"id": panel_id, "owner_id": owner_id, "created_at": timestamp, "updated_at": timestamp, "definition": definition}


def get_panel(panel_id: str, owner_id: int) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM panels WHERE id = ? AND owner_id = ?", (panel_id, owner_id)).fetchone()
        return _row_to_panel(row) if row else None


def list_panels(owner_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM panels WHERE owner_id = ? ORDER BY updated_at DESC", (owner_id,)).fetchall()
        return [_row_to_panel(row) for row in rows]


def update_panel(panel_id: str, owner_id: int, definition: dict[str, Any]) -> Optional[dict[str, Any]]:
    with connect() as conn:
        cursor = conn.execute(
            "UPDATE panels SET definition = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
            (json.dumps(definition, ensure_ascii=False), now_iso(), panel_id, owner_id),
        )
        if cursor.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM panels WHERE id = ? AND owner_id = ?", (panel_id, owner_id)).fetchone()
        return _row_to_panel(row)
