from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

DB_PATH = Path("english_boss.db")

SCHEMA = r"""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
  user_id    INTEGER PRIMARY KEY,
  username   TEXT,
  tz         TEXT DEFAULT 'America/Chicago',
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS words (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level TEXT, en TEXT, fa TEXT, pos TEXT,
  synonyms TEXT, examples TEXT
);
CREATE TABLE IF NOT EXISTS user_words (
  user_id INTEGER, word_id INTEGER,
  box INTEGER DEFAULT 1,
  next_due TEXT,
  successes INTEGER DEFAULT 0,
  failures INTEGER DEFAULT 0,
  last_reviewed TEXT,
  PRIMARY KEY (user_id, word_id)
);
"""

def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db() -> None:
    with connect() as con:
        con.executescript(SCHEMA)

def upsert_user(user_id: int, username: Optional[str], tz: Optional[str] = None) -> None:
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO users(user_id, username, tz) VALUES(?,?,?)",
                    (user_id, username, tz or 'America/Chicago'))
        if tz:
            con.execute("UPDATE users SET tz=? WHERE user_id=?", (tz, user_id))

def insert_word(row: Dict[str, Any]) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO words(level,en,fa,pos,synonyms,examples) VALUES(?,?,?,?,?,?)",
            (row.get('level'), row.get('en'), row.get('fa'), row.get('pos'), row.get('synonyms'), row.get('examples'))
        )
        return cur.lastrowid

def ensure_user_word(user_id: int, word_id: int, next_due_iso: str) -> None:
    with connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO user_words(user_id, word_id, box, next_due) VALUES(?,?,1,?)",
            (user_id, word_id, next_due_iso)
        )

def get_due_words(user_id: int, limit: int = 10) -> List[sqlite3.Row]:
    now_iso = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        cur = con.execute(
            """
            SELECT uw.word_id, uw.box, w.en, w.fa, w.level, w.pos, w.synonyms, w.examples
            FROM user_words uw
            JOIN words w ON w.id = uw.word_id
            WHERE uw.user_id=? AND IFNULL(uw.next_due, '') <= ?
            ORDER BY IFNULL(uw.next_due, '') ASC
            LIMIT ?
            """,
            (user_id, now_iso, limit)
        )
        return cur.fetchall()

def get_user_word_box(user_id: int, word_id: int) -> int:
    with connect() as con:
        cur = con.execute(
            "SELECT box FROM user_words WHERE user_id=? AND word_id=?",
            (user_id, word_id)
        ).fetchone()
        return int(cur["box"]) if cur and cur["box"] is not None else 1

def update_review(user_id: int, word_id: int, new_box: int, next_due_iso: str, success: bool) -> None:
    with connect() as con:
        con.execute(
            """
            UPDATE user_words SET box=?, next_due=?, last_reviewed=datetime('now'),
                successes = successes + ?, failures = failures + ?
            WHERE user_id=? AND word_id=?
            """,
            (new_box, next_due_iso, 1 if success else 0, 0 if success else 1, user_id, word_id)
        )
