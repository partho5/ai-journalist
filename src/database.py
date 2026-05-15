"""
SQLite state store.

Tables
------
articles  : every URL ever scraped, with processing status
fb_tokens : persisted Facebook tokens (user + page)
"""

import sqlite3
from contextlib import contextmanager
from typing import Dict, Generator, List, Optional

DB_PATH = "data/state.db"

# Article status progression:
#   pending → filtered_out | approved → published | error
_CREATE_ARTICLES = """
CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name   TEXT    NOT NULL,
    url           TEXT    UNIQUE NOT NULL,
    headline      TEXT,
    body_text     TEXT,
    image_url     TEXT,
    scraped_at    TEXT    DEFAULT (datetime('now')),
    status        TEXT    DEFAULT 'pending',
    canonical_url TEXT,
    fb_post_id    TEXT,
    published_at  TEXT,
    error_message TEXT
)
"""

_CREATE_TOKENS = """
CREATE TABLE IF NOT EXISTS fb_tokens (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
)
"""


@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    import os
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.execute(_CREATE_ARTICLES)
        conn.execute(_CREATE_TOKENS)


def reset_db() -> None:
    """Delete all scraped articles so every URL is treated as unseen on next run."""
    with _connect() as conn:
        conn.execute("DELETE FROM articles")


def is_url_seen(url: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone()
        return row is not None


def save_article(
    source_name: str,
    url: str,
    headline: str,
    body_text: str,
    image_url: Optional[str],
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO articles (source_name, url, headline, body_text, image_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source_name, url, headline, body_text, image_url),
        )


def count_by_status(status: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE status = ?", (status,)
        ).fetchone()
        return row[0]


def get_approved_articles() -> List[Dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE status = 'approved' ORDER BY scraped_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def expire_old_articles(max_age_hours: int) -> int:
    modifier = f"-{max_age_hours} hours"
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE articles SET status = 'expired' "
            "WHERE status = 'approved' "
            "AND scraped_at < datetime('now', ?)",
            (modifier,),
        )
        return cur.rowcount


def get_recent_headlines(n: int) -> List[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT headline FROM articles ORDER BY scraped_at DESC LIMIT ?", (n,)
        ).fetchall()
        return [r["headline"] for r in rows if r["headline"]]


def trim_old_articles(max_rows: int = 100, keep: int = 80) -> int:
    """When total rows >= max_rows, delete the oldest non-active rows down to `keep`."""
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if count < max_rows:
            return 0
        to_delete = count - keep
        cur = conn.execute(
            """
            DELETE FROM articles
            WHERE id IN (
                SELECT id FROM articles
                WHERE status NOT IN ('pending', 'approved')
                ORDER BY scraped_at ASC
                LIMIT ?
            )
            """,
            (to_delete,),
        )
        return cur.rowcount


def get_pending_articles() -> List[Dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE status = 'pending' ORDER BY scraped_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def update_status(url: str, status: str, extra: Optional[Dict] = None) -> None:
    fields = {"status": status}
    if extra:
        fields.update(extra)
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [url]
    with _connect() as conn:
        conn.execute(
            f"UPDATE articles SET {set_clause} WHERE url = ?", values  # noqa: S608
        )



def mark_published(url: str, fb_post_id: str) -> None:
    update_status(
        url,
        "published",
        {"fb_post_id": fb_post_id, "published_at": "datetime('now')"},
    )


def mark_error(url: str, message: str) -> None:
    update_status(url, "error", {"error_message": message[:500]})


# ── Token helpers ────────────────────────────────────────────────────────────

def get_token(key: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM fb_tokens WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def save_token(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO fb_tokens (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = datetime('now')
            """,
            (key, value),
        )
