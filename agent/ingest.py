"""Ingestion: discover new issues via the RSS feed, get each issue's text.

We never hardcode a single issue URL (those carry short-lived tokens and point
at one day). Instead we poll the feed, then process every entry we haven't
already stored — so a missed day is picked up on the next run as long as it's
still in the feed.
"""
import time

import feedparser
import requests
from bs4 import BeautifulSoup

from . import config


def fetch_feed_entries():
    """Return feed entries newest-last (chronological)."""
    parsed = feedparser.parse(config.STRICTLYVC_FEED_URL,
                              request_headers={"User-Agent": config.USER_AGENT})
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(
            f"Could not read feed at {config.STRICTLYVC_FEED_URL}: {parsed.bozo_exception}"
        )
    # feeds are newest-first; reverse so we process oldest unseen first.
    return list(reversed(parsed.entries))


def entry_issue_id(entry) -> str:
    return entry.get("id") or entry.get("guid") or entry.get("link")


def entry_published_date(entry) -> str:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return time.strftime("%Y-%m-%d", t) if t else ""


def entry_text(entry) -> str:
    """Prefer full content embedded in the feed; fall back to fetching the page."""
    content = entry.get("content")
    if content and content[0].get("value"):
        html = content[0]["value"]
        if len(html) > 2000:  # looks like the full body, not a teaser
            return _html_to_text(html)

    summary = entry.get("summary", "")
    if len(summary) > 2000:
        return _html_to_text(summary)

    # Fall back to scraping the public post page.
    link = entry.get("link")
    if not link:
        return _html_to_text(summary)
    resp = requests.get(link, headers={"User-Agent": config.USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return _page_to_text(resp.text)


def _html_to_text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def _page_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    return main.get_text("\n", strip=True)
