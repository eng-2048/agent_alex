"""Configuration, all overridable via environment variables.

Locally you can drop these into a .env file (see .env.example); in GitHub
Actions they come from repo Secrets / Variables.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional; Actions injects env directly.

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("AGENT_DB_PATH", ROOT / "data" / "agent.db"))
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SEEDS_PATH = ROOT / "seeds" / "aliases.json"

# --- Secrets (required at run time) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# --- Source ---
# StrictlyVC runs on beehiiv. beehiiv exposes a public RSS feed per publication.
# CONFIRM this URL once: open the newsletter homepage, view source, and look for
#   <link rel="alternate" type="application/rss+xml" href="...">
# then set STRICTLYVC_FEED_URL to that value.
STRICTLYVC_FEED_URL = os.getenv(
    "STRICTLYVC_FEED_URL",
    "https://rss.beehiiv.com/feeds/9OgS3Lw7Mu.xml",  # <-- placeholder, verify
)

# --- Extraction model ---
# Sonnet is a good default for messy prose; Haiku is cheaper if volume grows.
EXTRACT_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-6")

# --- Counting / alerting semantics (the decisions we locked in) ---
THRESHOLD = int(os.getenv("AGENT_THRESHOLD", "5"))        # deals to be "prolific"
ALERT_WINDOW_DAYS = int(os.getenv("AGENT_WINDOW_DAYS", "90"))  # rolling window
USER_AGENT = os.getenv("AGENT_USER_AGENT", "Agent/0.1 (VC firm tracker)")


def require_secrets():
    missing = [k for k, v in {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "SLACK_WEBHOOK_URL": SLACK_WEBHOOK_URL,
    }.items() if not v]
    if missing:
        raise SystemExit(f"Missing required env vars: {', '.join(missing)}")
