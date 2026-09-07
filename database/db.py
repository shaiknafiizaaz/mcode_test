"""SQLite persistence for history, mock-test progress and settings.

Tables:
    history        - analysis sessions (searchable, deletable)
    code_stats     - per-code practice accuracy (wrong-answer learning)
    mock_sessions  - mock test attempts (total tests, average score)
    settings       - key/value settings
"""
from __future__ import annotations

import json
import os
import sqlite3
import datetime
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_default_db_path = (
    os.path.join("/tmp", "tenet_app.db")
    if os.environ.get("VERCEL")
    else os.path.join(BASE_DIR, "database", "app.db")
)
DB_PATH = os.environ.get('TENET_DB_PATH', _default_db_path)


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """Connection that commits on success and always closes."""
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                input_type TEXT NOT NULL,
                input_preview TEXT,
                detected_fields TEXT,
                suggested_codes TEXT,
                warnings TEXT,
                corrections TEXT
            );
            CREATE TABLE IF NOT EXISTS code_stats (
                code TEXT PRIMARY KEY,
                attempts INTEGER NOT NULL DEFAULT 0,
                correct INTEGER NOT NULL DEFAULT 0,
                wrong INTEGER NOT NULL DEFAULT 0,
                last_attempted TEXT
            );
            CREATE TABLE IF NOT EXISTS mock_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                category TEXT NOT NULL,
                total INTEGER NOT NULL,
                correct INTEGER NOT NULL,
                score REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def add_history(
    input_type: str,
    input_preview: str,
    detected_fields: List[str],
    suggested_codes: List[Dict[str, str]],
    warnings: List[str],
    corrections: Optional[Dict[str, Any]] = None,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO history (created_at, input_type, input_preview, detected_fields, suggested_codes, warnings, corrections)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _now(),
                input_type,
                input_preview[:500],
                json.dumps(detected_fields),
                json.dumps(suggested_codes),
                json.dumps(warnings),
                json.dumps(corrections) if corrections else None,
            ),
        )
        return int(cur.lastrowid)


def list_history(search: str = "", limit: int = 200) -> List[Dict[str, Any]]:
    with _conn() as conn:
        if search:
            rows = conn.execute(
                "SELECT * FROM history WHERE input_preview LIKE ? OR suggested_codes LIKE ? OR detected_fields LIKE ?"
                " ORDER BY id DESC LIMIT ?",
                (f"%{search}%", f"%{search}%", f"%{search}%", limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        for key in ("detected_fields", "suggested_codes", "warnings", "corrections"):
            try:
                item[key] = json.loads(item[key]) if item[key] else None
            except (TypeError, json.JSONDecodeError):
                item[key] = None
        out.append(item)
    return out


def delete_history(history_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM history WHERE id = ?", (history_id,))
        return cur.rowcount > 0


def clear_history() -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM history")


# ---------------------------------------------------------------------------
# Mock test progress
# ---------------------------------------------------------------------------

def record_answer(code: str, correct: bool) -> None:
    now = _now()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM code_stats WHERE code = ?", (code,)).fetchone()
        if row:
            conn.execute(
                "UPDATE code_stats SET attempts = attempts + 1, correct = correct + ?, wrong = wrong + ?, last_attempted = ? WHERE code = ?",
                (1 if correct else 0, 0 if correct else 1, now, code),
            )
        else:
            conn.execute(
                "INSERT INTO code_stats (code, attempts, correct, wrong, last_attempted) VALUES (?, 1, ?, ?, ?)",
                (code, 1 if correct else 0, 0 if correct else 1, now),
            )


def get_code_stats() -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM code_stats ORDER BY attempts DESC").fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["accuracy"] = round((item["correct"] / item["attempts"] * 100), 1) if item["attempts"] else 0.0
        out.append(item)
    return out


def get_weak_codes(min_attempts: int = 1, max_results: int = 30) -> List[Dict[str, Any]]:
    """Codes needing practice: poor accuracy or any wrong answers."""
    stats = [s for s in get_code_stats() if s["attempts"] >= min_attempts]
    weak = [s for s in stats if s["accuracy"] < 70.0 or s["wrong"] > 0]
    weak.sort(key=lambda s: (s["accuracy"], -s["wrong"]))
    return weak[:max_results]


def add_mock_session(mode: str, category: str, total: int, correct: int) -> Dict[str, Any]:
    score = round(correct / total * 100, 1) if total else 0.0
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO mock_sessions (created_at, mode, category, total, correct, score) VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), mode, category, total, correct, score),
        )
        return {"id": int(cur.lastrowid), "score": score}


def get_mock_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM mock_sessions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_learning_stats() -> Dict[str, Any]:
    """Dashboard learning statistics."""
    with _conn() as conn:
        sessions = conn.execute("SELECT COUNT(*) AS n, AVG(score) AS avg_score FROM mock_sessions").fetchone()
        stats = conn.execute("SELECT * FROM code_stats").fetchall()
    total_tests = sessions["n"] or 0
    avg_score = round(sessions["avg_score"], 1) if sessions["avg_score"] is not None else 0.0
    mastered = 0
    needs_practice = 0
    for s in stats:
        acc = (s["correct"] / s["attempts"] * 100) if s["attempts"] else 0.0
        if s["attempts"] >= 3 and acc >= 90.0:
            mastered += 1
        if acc < 70.0 or s["wrong"] > 0:
            needs_practice += 1
    weak = [s for s in stats if (s["wrong"] or 0) > 0]
    weak.sort(key=lambda x: x["last_attempted"] or "", reverse=True)
    recent_wrong = [
        {"code": s["code"], "wrong": s["wrong"], "accuracy": round(s["correct"] / s["attempts"] * 100, 1) if s["attempts"] else 0.0}
        for s in weak[:8]
    ]
    return {
        "total_tests": total_tests,
        "average_score": avg_score,
        "codes_mastered": mastered,
        "codes_needing_practice": needs_practice,
        "recent_wrong": recent_wrong,
        "codes_practiced": len(stats),
    }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key: str, default: Any = None) -> Any:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return row["value"]


def set_setting(key: str, value: Any) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


def get_all_settings() -> Dict[str, Any]:
    with _conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    out = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except (TypeError, json.JSONDecodeError):
            out[r["key"]] = r["value"]
    return out
