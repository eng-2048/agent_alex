"""Query interface (CLI).

  python -m agent.query list                      all firms, all-time counts
  python -m agent.query list --window 180         counts over last 180 days
  python -m agent.query prolific --min 5 --window 180

The window is independent of the alert window — querying "last 6 months" does
not change what the alerter watches.
"""
from __future__ import annotations

import argparse

from .db import connect, init_db
from .queries import count_firms as _counts


def _print(rows, window_days):
    label = f"last {window_days} days" if window_days else "all time"
    if not rows:
        print(f"No firms found ({label}).")
        return
    print(f"Firm appearances ({label}):")
    width = max(len(r["name"]) for r in rows)
    for r in rows:
        print(f"  {r['name']:<{width}}  {r['n']}")


def main():
    p = argparse.ArgumentParser(description="Query tracked VC firms.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list all firms with appearance counts")
    pl.add_argument("--window", type=int, default=None, help="window in days")

    pp = sub.add_parser("prolific", help="firms over a threshold within a window")
    pp.add_argument("--min", type=int, default=5)
    pp.add_argument("--window", type=int, default=180)

    args = p.parse_args()
    conn = connect()
    init_db(conn)
    if args.cmd == "list":
        _print(_counts(conn, args.window), args.window)
    else:
        _print(_counts(conn, args.window, args.min), args.window)


if __name__ == "__main__":
    main()
