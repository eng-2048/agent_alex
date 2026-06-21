"""Daily orchestrator. Run by the GitHub Action (or manually):

    python -m agent.run

Processes every feed entry not already stored, then runs alerts. Per-issue
failures don't mark the issue as parsed, so they retry on the next run.
"""
from . import config, ingest
from .db import connect, init_db, now_iso
from .extract import extract_deals
from .record import record_deals
from .alert import process_alerts


def issue_seen(conn, issue_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM issues WHERE issue_id = ?", (issue_id,)
    ).fetchone() is not None


def main():
    config.require_secrets()
    conn = connect()
    init_db(conn)

    entries = ingest.discover_entries()
    touched: set[int] = set()
    processed = 0

    for entry in entries:
        issue_id = ingest.entry_issue_id(entry)
        if not issue_id or issue_seen(conn, issue_id):
            continue
        issue_date = ingest.entry_published_date(entry)
        try:
            text = ingest.entry_text(entry)
            deals = extract_deals(text)
            # Insert the issue row first so deals can reference it (FK); a failure
            # below rolls back both, leaving the issue unseen for the next run.
            conn.execute(
                "INSERT INTO issues(issue_id, url, published_date, fetched_at, status) "
                "VALUES (?, ?, ?, ?, 'parsed')",
                (issue_id, entry.get("link"), issue_date, now_iso()),
            )
            touched |= record_deals(conn, issue_id, issue_date, deals)
            conn.commit()
            processed += 1
            print(f"[ok] {issue_date} {issue_id} — {len(deals)} deals")
        except Exception as e:  # noqa: BLE001 — keep going, retry next run
            conn.rollback()
            print(f"[skip] {issue_id} — {type(e).__name__}: {e}")

    alerted = process_alerts(conn, touched)
    print(f"\nProcessed {processed} new issue(s); "
          f"{len(touched)} firm(s) updated; {len(alerted)} alert(s) fired.")
    if alerted:
        print("Alerted:", ", ".join(alerted))


if __name__ == "__main__":
    main()
