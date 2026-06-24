"""SQLite access: open a connection, create the schema, seed aliases."""
import json
import sqlite3
from datetime import datetime, timezone

from . import config


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(config.SCHEMA_PATH.read_text())
    conn.commit()
    _migrate(conn)
    _seed_aliases(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring older databases up to date (e.g. add the `source` column)."""
    for table in ("appearances", "issues"):
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        if "source" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN source TEXT")
    conn.commit()


def _seed_aliases(conn: sqlite3.Connection) -> None:
    """Load seeds/aliases.json so well-known variants collapse from day one.

    Each entry maps a canonical firm name -> list of aliases. Idempotent.
    """
    if not config.SEEDS_PATH.exists():
        return
    seeds = json.loads(config.SEEDS_PATH.read_text())
    for canonical, aliases in seeds.items():
        firm_id = _get_or_create_firm(conn, canonical)
        for alias in [canonical, *aliases]:
            conn.execute(
                "INSERT OR IGNORE INTO firm_aliases(alias, firm_id) VALUES (?, ?)",
                (alias.strip().lower(), firm_id),
            )
    conn.commit()


def _get_or_create_firm(conn: sqlite3.Connection, canonical: str,
                        is_individual: bool = False) -> int:
    row = conn.execute(
        "SELECT firm_id FROM firms WHERE canonical_name = ?", (canonical,)
    ).fetchone()
    if row:
        return row["firm_id"]
    cur = conn.execute(
        "INSERT INTO firms(canonical_name, is_individual, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?)",
        (canonical, int(is_individual), now_iso(), now_iso()),
    )
    return cur.lastrowid
