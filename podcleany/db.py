"""SQLite en modo WAL, migraciones y cola de jobs (reclamo atómico)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
CREATE TABLE channels (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    rss_url TEXT NOT NULL UNIQUE,
    cover_path TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE episodes (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    guid TEXT,
    audio_url TEXT,
    description TEXT,
    cover_path TEXT,
    duration_s REAL,
    original_path TEXT,
    clean_path TEXT,
    clean_duration_s REAL,
    removed_s REAL,
    clean_stale INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    metrics TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(channel_id, guid)
);
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('process','render')),
    episode_id INTEGER REFERENCES episodes(id),
    url TEXT,
    dedupe_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
    stage TEXT,
    progress REAL NOT NULL DEFAULT 0,
    message TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    worker_id TEXT,
    heartbeat_at REAL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    started_at TEXT,
    finished_at TEXT
);
CREATE UNIQUE INDEX jobs_active_dedupe ON jobs(dedupe_key) WHERE status IN ('queued','running','done');
CREATE INDEX jobs_queue ON jobs(status, id);
CREATE TABLE ad_fingerprints (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER REFERENCES channels(id),
    kind TEXT NOT NULL CHECK (kind IN ('ad','protected')),
    label TEXT,
    duration_s REAL NOT NULL,
    n_hashes INTEGER NOT NULL,
    hashes BLOB NOT NULL,
    source_episode_id INTEGER REFERENCES episodes(id),
    enabled INTEGER NOT NULL DEFAULT 1,
    hits INTEGER NOT NULL DEFAULT 0,
    false_positives INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE ad_segments (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    score REAL NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('fingerprint','llm','signals','user')),
    evidence TEXT NOT NULL DEFAULT '{}',
    auto_decision TEXT NOT NULL CHECK (auto_decision IN ('remove','review')),
    user_decision TEXT CHECK (user_decision IN ('keep','remove')),
    fingerprint_id INTEGER REFERENCES ad_fingerprints(id),
    history TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ad_segments_episode ON ad_segments(episode_id, start_s);
CREATE INDEX ad_fingerprints_enabled ON ad_fingerprints(enabled, kind);
"""),
]


def connect(path: Path | str) -> sqlite3.Connection:
    # isolation_level=None: control manual de transacciones (BEGIN IMMEDIATE)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    for version, sql in MIGRATIONS:
        if version in done:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _split(sql):
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return max(v for v, _ in MIGRATIONS)


def _split(sql: str) -> list[str]:
    return [s.strip() for s in sql.split(";\n") if s.strip()]


def open_db(cfg) -> sqlite3.Connection:
    cfg.ensure_dirs()
    conn = connect(cfg.db_path)
    migrate(conn)
    return conn


# ---------------------------------------------------------------- cola de jobs
def enqueue(conn, kind: str, dedupe_key: str, url: str | None = None, episode_id: int | None = None):
    """Inserta un job 'queued'. Devuelve (job_id, duplicate)."""
    try:
        cur = conn.execute(
            "INSERT INTO jobs(kind, url, episode_id, dedupe_key) VALUES (?,?,?,?)",
            (kind, url, episode_id, dedupe_key),
        )
        return cur.lastrowid, False
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT id FROM jobs WHERE dedupe_key=? AND status IN ('queued','running','done') ORDER BY id DESC LIMIT 1",
            (dedupe_key,),
        ).fetchone()
        return row["id"], True


def claim_job(conn, worker_id: str):
    """Reclama el job más antiguo con BEGIN IMMEDIATE (sin procesamiento duplicado)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        conn.execute(
            "UPDATE jobs SET status='running', worker_id=?, attempts=attempts+1, heartbeat_at=?, "
            "started_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (worker_id, time.time(), row["id"]),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()


def requeue_stale(conn, stale_s: float) -> int:
    """Devuelve a la cola los jobs 'running' cuyo worker dejó de latir (fallo del worker)."""
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.execute(
        "UPDATE jobs SET status='queued', worker_id=NULL, message='reanudado tras fallo del worker' "
        "WHERE status='running' AND heartbeat_at < ?",
        (time.time() - stale_s,),
    )
    conn.execute("COMMIT")
    return cur.rowcount


def update_job(conn, job_id: int, **fields) -> None:
    fields["heartbeat_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def touch_episode(conn, episode_id: int, **fields) -> None:
    fields["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE episodes SET {cols} WHERE id=?", (*fields.values(), episode_id))


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=float)
