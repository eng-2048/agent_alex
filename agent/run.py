"""Daily orchestrator. Run by the GitHub Action (or manually):

    python -m agent.run

Pulls recent issues from every enabled source, ingests any not already stored,
then runs alerts. Per-issue failures don't mark the issue as parsed, so they
retry on the next run.
"""
from . import config, ingest, sources
from .db import connect, init_db, now_iso
from .extract import extract_deals
from .record import record_deals
from .alert import process_alerts


def issue_seen(conn, issue_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM issues WHERE issue_id = ?", (issue_id,)
    ).fetchone() is not None


def process_entries(conn, entries) -> tuple[int, set[int]]:
    """Ingest a list of normalized entries. Returns (count_processed, touched_firms).

    Shared by the daily run and the backfill runner.
    """
    touched: set[int] = set()
    processed = 0
    for entry in entries:
        issue_id = ingest.entry_issue_id(entry)
        if not issue_id or issue_seen(conn, issue_id):
            continue
        source = entry.get("source", "unknown")
        issue_date = ingest.entry_published_date(entry)
        try:
            text = ingest.entry_text(entry)
            deals = extract_deals(text)
            conn.execute(
                "INSERT INTO issues(issue_id, url, published_date, fetched_at, source, status) "
                "VALUES (?, ?, ?, ?, ?, 'parsed')",
                (issue_id, entry.get("link"), issue_date, now_iso(), source),
            )
            touched |= record_deals(conn, issue_id, issue_date, deals, source)
            conn.commit()
            processed += 1
            print(f"[ok] {source} {issue_date} — {len(deals)} deals")
        except Exception as e:  # noqa: BLE001 — keep going, retry next run
            conn.rollback()
            print(f"[skip] {source} {issue_id} — {type(e).__name__}: {e}")
    return processed, touched


def main():
    config.require_secrets()
    conn = connect()
    init_db(conn)

    entries = sources.collect_entries(config.ENABLED_SOURCES)
    processed, touched = process_entries(conn, entries)

    alerted = process_alerts(conn, touched)
    print(f"\nProcessed {processed} new issue(s); "
          f"{len(touched)} firm(s) updated; {len(alerted)} alert(s) fired.")
    if alerted:
        print("Alerted:", ", ".join(alerted))


if __name__ == "__main__":
    main()
