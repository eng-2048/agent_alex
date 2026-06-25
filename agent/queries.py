"""Shared read queries, used by both the CLI (query.py) and the Slack
server (server.py) so the counting logic lives in exactly one place.
"""
from __future__ import annotations

import datetime as dt


def count_firms(conn, window_days=None, min_count=None):
    """Return rows of (name, n) for firm appearance counts.

    window_days: restrict to appearances within the trailing N days (None = all time).
    min_count:   only firms with at least this many appearances (None = no floor).
    """
    params = []
    where = ""
    if window_days:
        cutoff = (dt.date.today() - dt.timedelta(days=window_days)).isoformat()
        where = "WHERE a.issue_date >= ?"
        params.append(cutoff)
    having = ""
    if min_count:
        having = "HAVING n >= ?"
        params.append(min_count)
    sql = (
        "SELECT f.canonical_name AS name, COUNT(*) AS n "
        "FROM appearances a JOIN firms f ON a.firm_id = f.firm_id "
        f"{where} GROUP BY f.firm_id {having} ORDER BY n DESC, name ASC"
    )
    return conn.execute(sql, params).fetchall()
