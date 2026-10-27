"""SQLite schema and connection helper for per-person profiles."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "profiles.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    skill TEXT NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE(profile_id, skill)
);
CREATE TABLE IF NOT EXISTS profile_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    kind TEXT NOT NULL,
    label TEXT,
    file_path TEXT,
    extracted_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_job_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    label TEXT NOT NULL,
    is_custom INTEGER NOT NULL DEFAULT 0,
    possible INTEGER NOT NULL DEFAULT 0,
    desired INTEGER NOT NULL DEFAULT 0,
    dismissed INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(profile_id, label)
);
CREATE TABLE IF NOT EXISTS job_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    job_url TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    text TEXT NOT NULL,
    decision TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(profile_id, job_url)
);
"""


def connect(db_path=DB_PATH):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn):
    """Add columns introduced after a table's first release, for DBs created before they existed."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(profile_job_types)").fetchall()}
    if "dismissed" not in cols:
        conn.execute("ALTER TABLE profile_job_types ADD COLUMN dismissed INTEGER NOT NULL DEFAULT 0")


def init_db(db_path=DB_PATH):
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
