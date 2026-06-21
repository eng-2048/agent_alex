"""Slack slash-command server for querying tracked firms.

This runs as a small always-on web service (e.g. a Render web service). It does
NOT ingest anything — the daily GitHub Action still owns ingestion and commits
the database. This service just READS that committed `data/agent.db` over HTTPS
per request and answers Slack queries, so there's no second copy of the data.

Slash command examples (configured in Slack as e.g. `/firms`):
    /firms                 -> all firms, all-time, by count
    /firms list 180        -> all firms over the last 180 days
    /firms prolific        -> firms with >= THRESHOLD in the last 180 days
    /firms prolific 5 90   -> firms with >= 5 in the last 90 days
    /firms help
"""
import hashlib
import hmac
import os
import sqlite3
import tempfile
import time

import requests
from flask import Flask, jsonify, request

from . import config
from .queries import count_firms

app = Flask(__name__)

_HELP = (
    "*Usage:*\n"
    "• `/firms` — all firms, all-time, ranked by appearances\n"
    "• `/firms list 180` — all firms over the last 180 days\n"
    "• `/firms prolific` — firms at or above the alert threshold (last 180 days)\n"
    "• `/firms prolific 5 90` — firms with ≥5 appearances in the last 90 days"
)

# Small cache so repeated queries don't re-download the DB every time.
_CACHE = {"path": None, "ts": 0.0}
_CACHE_TTL = 300  # seconds


# ---- Slack request authenticity ----
def _verify_slack(req) -> bool:
    secret = config.SLACK_SIGNING_SECRET
    if not secret:
        return True  # no secret set (local dev) — allow
    ts = req.headers.get("X-Slack-Request-Timestamp", "")
    sig = req.headers.get("X-Slack-Signature", "")
    try:
        if not ts or abs(time.time() - int(ts)) > 300:
            return False  # stale -> replay protection
    except ValueError:
        return False
    base = f"v0:{ts}:{req.get_data(as_text=True)}"
    mine = "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mine, sig)


# ---- Fetch the committed database ----
def _fetch_db_bytes() -> bytes:
    repo, branch, path = config.GITHUB_REPO, config.GITHUB_BRANCH, config.GITHUB_DB_PATH
    headers = {"User-Agent": config.USER_AGENT}
    if config.GITHUB_TOKEN:  # private repo
        url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
        headers["Accept"] = "application/vnd.github.raw"
    else:  # public repo
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.content


def _db_path() -> str:
    now = time.time()
    if _CACHE["path"] and now - _CACHE["ts"] < _CACHE_TTL and os.path.exists(_CACHE["path"]):
        return _CACHE["path"]
    fd, path = tempfile.mkstemp(suffix=".db")
    with os.fdopen(fd, "wb") as f:
        f.write(_fetch_db_bytes())
    _CACHE["path"], _CACHE["ts"] = path, now
    return path


def _open():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


# ---- Command parsing + formatting ----
def _parse(text: str):
    """Return (window_days, min_count). Raises ValueError on bad numbers."""
    parts = (text or "").strip().split()
    if not parts or parts[0] in ("list", "all"):
        window = int(parts[1]) if len(parts) > 1 else None
        return window, None
    if parts[0] == "prolific":
        min_count = int(parts[1]) if len(parts) > 1 else config.THRESHOLD
        window = int(parts[2]) if len(parts) > 2 else 180
        return window, min_count
    # Unknown verb: treat as all-time list.
    return None, None


def _format(rows, window_days, limit: int = 30) -> str:
    label = f"last {window_days} days" if window_days else "all time"
    if not rows:
        return f"No firms tracked yet ({label})."
    lines = [f"*Firm appearances — {label}:*"]
    for r in rows[:limit]:
        lines.append(f"• {r['name']} — {r['n']}")
    if len(rows) > limit:
        lines.append(f"_…and {len(rows) - limit} more._")
    return "\n".join(lines)


# ---- Routes ----
@app.route("/slack/firms", methods=["POST"])
def firms():
    if not _verify_slack(request):
        return ("invalid signature", 403)
    text = (request.form.get("text") or "").strip()
    if text == "help":
        return jsonify({"response_type": "ephemeral", "text": _HELP})
    try:
        window, min_count = _parse(text)
    except ValueError:
        return jsonify({"response_type": "ephemeral", "text": _HELP})
    try:
        rows = count_firms(_open(), window, min_count)
    except Exception as e:  # noqa: BLE001
        return jsonify({"response_type": "ephemeral",
                        "text": f"Couldn't read the data right now: {e}"})
    return jsonify({"response_type": "ephemeral", "text": _format(rows, window)})


@app.route("/health")
def health():
    return "ok"
