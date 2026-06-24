"""Backfill a date range across newsletters. Examples:

    # 1-month test window across all sources, start clean:
    python -m agent.backfill --since 2026-05-22 --reset

    # only the deal-heavy sources, a specific range:
    python -m agent.backfill --since 2026-01-01 --until 2026-06-22 --sources prorata,termsheet

By default it does NOT fire Slack alerts (a backfill would otherwise blast the
channel); pass --alerts to run the alerter at the end.

The same cross-source dedup applies, so overlapping coverage of the same round
across newsletters collapses to a single appearance.
"""
import argparse
import datetime as dt

from . import config, sources
from .db import connect, init_db
from .run import process_entries
from .alert import process_alerts


def _reset(conn) -> None:
    for table in ("appearances", "deals", "issues", "alert_state"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    print("[reset] cleared appearances, deals, issues, alert_state "
          "(firms + aliases kept)")


def main():
    p = argparse.ArgumentParser(description="Backfill newsletters over a date range.")
    p.add_argument("--since", required=True, help="start date YYYY-MM-DD (inclusive)")
    p.add_argument("--until", default=dt.date.today().isoformat(),
                   help="end date YYYY-MM-DD (inclusive, default today)")
    p.add_argument("--sources", default=",".join(config.ENABLED_SOURCES),
                   help="comma-separated source names")
    p.add_argument("--reset", action="store_true",
                   help="wipe existing appearance data first (recommended for a clean rebuild)")
    p.add_argument("--alerts", action="store_true",
                   help="run Slack alerts after backfill (off by default)")
    args = p.parse_args()

    names = [s.strip() for s in args.sources.split(",") if s.strip()]
    conn = connect()
    init_db(conn)
    if args.reset:
        _reset(conn)

    print(f"[backfill] {args.since} → {args.until} across: {', '.join(names)}")
    entries = sources.collect_entries(names, args.since, args.until)
    print(f"[backfill] {len(entries)} candidate issue(s) found\n")

    processed, touched = process_entries(conn, entries)

    alerted = []
    if args.alerts:
        alerted = process_alerts(conn, touched)
    print(f"\n[backfill] done — {processed} issue(s) ingested; "
          f"{len(touched)} firm(s) updated; {len(alerted)} alert(s).")


if __name__ == "__main__":
    main()
