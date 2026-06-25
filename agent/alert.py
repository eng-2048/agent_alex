"""Alerting: fire a Slack message once when a firm crosses the threshold.

Counting respects config.ALERT_WINDOW_DAYS: 0 means all-time (every appearance
ever seen), a positive value means a rolling window of that many days. We alert
on the upward crossing and stay quiet afterward (re-arming only if the count
later drops below the threshold, which can't happen under all-time counting).
"""
from __future__ import annotations

import datetime as dt

import requests

from . import config
from .db import now_iso


def windowed_count(conn, firm_id: int, window_days: int) -> int:
    # window_days <= 0 (or None) means all-time: count every appearance seen.
    if not window_days or window_days <= 0:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM appearances WHERE firm_id = ?",
            (firm_id,),
        ).fetchone()["n"]
    cutoff = (dt.date.today() - dt.timedelta(days=window_days)).isoformat()
    return conn.execute(
        "SELECT COUNT(*) AS n FROM appearances "
        "WHERE firm_id = ? AND issue_date >= ?",
        (firm_id, cutoff),
    ).fetchone()["n"]


def _latest_deal(conn, firm_id: int, window_days: int):
    if not window_days or window_days <= 0:
        return conn.execute(
            "SELECT d.company, d.round_type, a.role, a.issue_date "
            "FROM appearances a JOIN deals d ON a.deal_id = d.deal_id "
            "WHERE a.firm_id = ? ORDER BY a.issue_date DESC LIMIT 1",
            (firm_id,),
        ).fetchone()
    cutoff = (dt.date.today() - dt.timedelta(days=window_days)).isoformat()
    return conn.execute(
        "SELECT d.company, d.round_type, a.role, a.issue_date "
        "FROM appearances a JOIN deals d ON a.deal_id = d.deal_id "
        "WHERE a.firm_id = ? AND a.issue_date >= ? "
        "ORDER BY a.issue_date DESC LIMIT 1",
        (firm_id, cutoff),
    ).fetchone()


def process_alerts(conn, touched_firm_ids: set[int]) -> list[str]:
    """Run the state machine for each touched firm. Return names alerted."""
    alerted = []
    for firm_id in touched_firm_ids:
        firm = conn.execute(
            "SELECT canonical_name FROM firms WHERE firm_id = ?", (firm_id,)
        ).fetchone()
        count = windowed_count(conn, firm_id, config.ALERT_WINDOW_DAYS)
        state = conn.execute(
            "SELECT armed FROM alert_state WHERE firm_id = ?", (firm_id,)
        ).fetchone()
        armed = True if state is None else bool(state["armed"])

        if count >= config.THRESHOLD and armed:
            _post_slack(conn, firm["canonical_name"], firm_id, count)
            conn.execute(
                "INSERT INTO alert_state(firm_id, armed, last_fired_at) VALUES (?, 0, ?) "
                "ON CONFLICT(firm_id) DO UPDATE SET armed = 0, last_fired_at = ?",
                (firm_id, now_iso(), now_iso()),
            )
            alerted.append(firm["canonical_name"])
        elif count < config.THRESHOLD and not armed:
            conn.execute(
                "INSERT INTO alert_state(firm_id, armed, last_fired_at) VALUES (?, 1, NULL) "
                "ON CONFLICT(firm_id) DO UPDATE SET armed = 1",
                (firm_id,),
            )
    conn.commit()
    return alerted


def _post_slack(conn, name: str, firm_id: int, count: int) -> None:
    latest = _latest_deal(conn, firm_id, config.ALERT_WINDOW_DAYS)
    ctx = ""
    if latest:
        verb = "led" if latest["role"] == "lead" else "backed"
        rnd = f" {latest['round_type']}" if latest["round_type"] else ""
        ctx = f" Latest: {verb} {latest['company']}'s{rnd} round ({latest['issue_date']})."
    span = (f"the last {config.ALERT_WINDOW_DAYS} days"
            if config.ALERT_WINDOW_DAYS and config.ALERT_WINDOW_DAYS > 0
            else "total")
    text = (f":rocket: *New prolific VC firm: {name}* — "
            f"{count} deals {span}.{ctx}")
    resp = requests.post(config.SLACK_WEBHOOK_URL, json={"text": text}, timeout=30)
    resp.raise_for_status()
