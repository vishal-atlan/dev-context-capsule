"""SQLite-backed capsule store. One DB per user at ~/.capsule/capsules.db."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from capsule.guardrails.sanitizer import is_stale

import os
DB_PATH = Path(os.environ.get("CAPSULE_DB_PATH", Path.home() / ".capsule" / "capsules.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS capsules (
            id          TEXT PRIMARY KEY,
            repo_name   TEXT NOT NULL,
            repo_path   TEXT NOT NULL,
            branch      TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            summary     TEXT NOT NULL,
            raw_json    TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_branch ON capsules(repo_path, branch)")
    conn.commit()
    return conn


def save_capsule(repo_path: str, branch: str, repo_name: str, summary: str, raw: dict) -> str:
    capsule_id = str(uuid.uuid4())[:8]
    captured_at = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO capsules VALUES (?,?,?,?,?,?,?)",
            (capsule_id, repo_name, repo_path, branch, captured_at, summary, json.dumps(raw)),
        )
    return capsule_id


def get_latest_capsule(repo_path: str, branch: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM capsules WHERE repo_path=? AND branch=? ORDER BY captured_at DESC LIMIT 1",
            (repo_path, branch),
        ).fetchone()
    return dict(row) if row else None


def list_capsules(repo_path: str = ".") -> str:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, branch, captured_at, summary FROM capsules WHERE repo_path=? ORDER BY captured_at DESC",
            (repo_path,),
        ).fetchall()
    if not rows:
        return "No capsules saved for this repo yet."
    lines = []
    for row in rows:
        stale_flag = " [STALE]" if is_stale(row["captured_at"]) else ""
        lines.append(f"[{row['id']}] {row['branch']} @ {row['captured_at'][:16]}{stale_flag}\n  {row['summary']}")
    return "\n\n".join(lines)


def get_all_capsules(repo_path: str = "") -> list[dict]:
    with _connect() as conn:
        query = "SELECT * FROM capsules"
        params: tuple = ()
        if repo_path:
            query += " WHERE repo_path=?"
            params = (repo_path,)
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_branch_history(repo_path: str, branch: str, limit: int = 3) -> list[dict]:
    """Return the last `limit` capsule summaries for a branch, newest first.

    Used by the capture agent to give the LLM memory of prior sessions on this branch.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, captured_at, summary FROM capsules "
            "WHERE repo_path=? AND branch=? ORDER BY captured_at DESC LIMIT ?",
            (repo_path, branch, limit),
        ).fetchall()
    return [
        {"id": row["id"], "captured_at": row["captured_at"][:16], "summary": row["summary"]}
        for row in rows
    ]


def delete_capsule(capsule_id: str) -> str:
    with _connect() as conn:
        deleted = conn.execute("DELETE FROM capsules WHERE id=?", (capsule_id,)).rowcount
    return f"Deleted capsule {capsule_id}." if deleted else f"No capsule found with id {capsule_id}."
