"""Resumable progress store (SQLite) for the roster scraper."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
  page_url      TEXT PRIMARY KEY,
  page_title    TEXT NOT NULL,
  source        TEXT NOT NULL DEFAULT '',
  status        TEXT NOT NULL DEFAULT 'pending',  -- pending | done | no_infobox | error
  attempts      INTEGER NOT NULL DEFAULT 0,
  last_error    TEXT,
  discovered_at TEXT,
  fetched_at    TEXT
);

CREATE TABLE IF NOT EXISTS characters (
  page_url        TEXT PRIMARY KEY REFERENCES pages(page_url),
  id              TEXT UNIQUE,
  name            TEXT,
  ja              TEXT,
  crew            TEXT,
  aliases_json    TEXT,
  img_source_url  TEXT,
  img_local_path  TEXT,
  image_status    TEXT NOT NULL DEFAULT 'pending'  -- pending | done | failed | no_image
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    with closing(conn.cursor()) as cur:
        cur.executescript(SCHEMA)
    conn.commit()
    return conn


def add_pages(conn: sqlite3.Connection, items) -> int:
    """items: iterable of (title, url, source). Returns number of newly inserted rows."""
    ts = now()
    with closing(conn.cursor()) as cur:
        before = cur.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        cur.executemany(
            "INSERT OR IGNORE INTO pages (page_url, page_title, source, discovered_at) VALUES (?, ?, ?, ?)",
            [(url, title, source, ts) for (title, url, source) in items],
        )
        after = cur.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    conn.commit()
    return after - before


def get_pending_pages(conn: sqlite3.Connection, max_attempts: int, limit=None):
    q = (
        "SELECT page_url, page_title FROM pages "
        "WHERE status='pending' OR (status='error' AND attempts < ?) "
        "ORDER BY rowid"
    )
    params = [max_attempts]
    if limit is not None:
        q += " LIMIT ?"
        params.append(limit)
    with closing(conn.cursor()) as cur:
        return cur.execute(q, params).fetchall()


def mark_page_done(conn: sqlite3.Connection, page_url: str):
    conn.execute(
        "UPDATE pages SET status='done', fetched_at=? WHERE page_url=?", (now(), page_url)
    )
    conn.commit()


def mark_page_no_infobox(conn: sqlite3.Connection, page_url: str):
    conn.execute(
        "UPDATE pages SET status='no_infobox', fetched_at=? WHERE page_url=?", (now(), page_url)
    )
    conn.commit()


def mark_page_error(conn: sqlite3.Connection, page_url: str, error: str):
    conn.execute(
        "UPDATE pages SET status='error', attempts=attempts+1, last_error=? WHERE page_url=?",
        (error[:500], page_url),
    )
    conn.commit()


def reset_pages(conn: sqlite3.Connection, statuses=("done", "no_infobox", "error")):
    placeholders = ",".join("?" for _ in statuses)
    conn.execute(
        f"UPDATE pages SET status='pending', attempts=0, last_error=NULL WHERE status IN ({placeholders})",
        statuses,
    )
    conn.commit()


def upsert_character(conn: sqlite3.Connection, page_url: str, data: dict):
    """data: {name, ja, crew, aliases (list), img_source_url}"""
    conn.execute(
        """
        INSERT INTO characters (page_url, name, ja, crew, aliases_json, img_source_url, image_status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
        ON CONFLICT(page_url) DO UPDATE SET
          name=excluded.name, ja=excluded.ja, crew=excluded.crew,
          aliases_json=excluded.aliases_json, img_source_url=excluded.img_source_url
        """,
        (
            page_url,
            data.get("name", ""),
            data.get("ja", ""),
            data.get("crew", ""),
            json.dumps(data.get("aliases", []), ensure_ascii=False),
            data.get("img_source_url"),
        ),
    )
    conn.commit()


def update_image_status(conn: sqlite3.Connection, page_url: str, status: str, local_path=None):
    conn.execute(
        "UPDATE characters SET image_status=?, img_local_path=? WHERE page_url=?",
        (status, local_path, page_url),
    )
    conn.commit()


def characters_missing_image(conn: sqlite3.Connection):
    with closing(conn.cursor()) as cur:
        return cur.execute(
            "SELECT page_url, img_source_url FROM characters "
            "WHERE image_status='pending' AND img_source_url IS NOT NULL"
        ).fetchall()


def all_done_characters(conn: sqlite3.Connection):
    with closing(conn.cursor()) as cur:
        return cur.execute(
            """
            SELECT c.page_url, c.name, c.ja, c.crew, c.aliases_json, c.img_local_path
            FROM characters c JOIN pages p ON p.page_url = c.page_url
            WHERE p.status = 'done'
            ORDER BY c.name COLLATE NOCASE
            """
        ).fetchall()


def status_summary(conn: sqlite3.Connection) -> dict:
    with closing(conn.cursor()) as cur:
        page_counts = dict(
            cur.execute("SELECT status, COUNT(*) FROM pages GROUP BY status").fetchall()
        )
        image_counts = dict(
            cur.execute("SELECT image_status, COUNT(*) FROM characters GROUP BY image_status").fetchall()
        )
        total = cur.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    return {"total": total, "pages": page_counts, "images": image_counts}
