"""Ingestion: find each new issue and get its text.

You can point this at EITHER a beehiiv RSS feed URL (…rss.beehiiv.com/feeds/X.xml)
OR the newsletter's plain homepage. Given a homepage we:
  1. try to auto-discover the RSS feed <link> in the page's <head>, and
  2. fall back to scraping issue links (…/p/slug) straight off the homepage.
Either way the rest of the pipeline sees the same normalized entries, processed
oldest-first so a missed day is caught up on the next run.
"""
from __future__ import annotations

import datetime as dt

import feedparser
import requests
from bs4 import BeautifulSoup

from . import config

HOMEPAGE = "https://newsletter.strictlyvc.com/"


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r


def _date_from_struct(t) -> str:
    return dt.datetime(*t[:6]).date().isoformat() if t else ""


def resolve_feed_url(source: str):
    """Return an RSS feed URL. Pass through if source already is one; otherwise
    treat source as a site page and discover the feed <link> in its <head>."""
    s = (source or "").strip()
    if not s:
        return None
    if s.endswith(".xml") or "rss.beehiiv.com" in s:
        return s
    try:
        soup = BeautifulSoup(_get(s).text, "html.parser")
        link = soup.find("link", attrs={"type": "application/rss+xml"})
        if link and link.get("href"):
            return link["href"]
    except Exception:
        pass
    return None


def strictlyvc_entries(since: str | None = None, until: str | None = None) -> list[dict]:
    """StrictlyVC entries (oldest-first), tagged with source and date-filtered.

    Note: this uses the RSS feed / homepage, which only reach recent issues.
    Deep backfill (e.g. to January) for StrictlyVC would need the beehiiv sitemap;
    we add that once the test window confirms the rest works.
    """
    feed_url = resolve_feed_url(config.STRICTLYVC_FEED_URL)
    entries: list[dict] = []
    if feed_url:
        parsed = feedparser.parse(
            feed_url, request_headers={"User-Agent": config.USER_AGENT})
        if parsed.entries:
            entries = [{
                "id": e.get("id") or e.get("link"),
                "link": e.get("link"),
                "published_date": _date_from_struct(
                    e.get("published_parsed") or e.get("updated_parsed")),
                "source": "strictlyvc",
                "_raw": e,
            } for e in parsed.entries]
    if not entries:
        entries = _scrape_homepage_entries()
    entries = [e for e in entries if _in_range(e.get("published_date"), since, until)]
    entries.sort(key=lambda e: e.get("published_date") or "")
    return entries


def _in_range(date_str, since, until) -> bool:
    # Unknown dates are kept (they get dated when the page is fetched).
    if not date_str:
        return True
    if since and date_str < since:
        return False
    if until and date_str > until:
        return False
    return True


def _scrape_homepage_entries() -> list[dict]:
    base = config.STRICTLYVC_FEED_URL
    if not base or base.endswith(".xml") or "rss.beehiiv.com" in base:
        base = HOMEPAGE
    soup = BeautifulSoup(_get(base).text, "html.parser")
    seen, entries = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/p/" not in href:
            continue
        url = href if href.startswith("http") else HOMEPAGE.rstrip("/") + "/" + href.lstrip("/")
        url = url.split("?")[0]
        if url in seen:
            continue
        seen.add(url)
        entries.append({"id": url, "link": url, "published_date": "",
                        "source": "strictlyvc", "_raw": None})
    return list(reversed(entries))  # homepage is newest-first


def _page_text_and_date(html: str):
    soup = BeautifulSoup(html, "html.parser")
    date = ""
    meta = (soup.find("meta", attrs={"property": "article:published_time"})
            or soup.find("meta", attrs={"name": "article:published_time"}))
    if meta and meta.get("content"):
        date = meta["content"][:10]
    if not date:
        t = soup.find("time")
        if t and t.get("datetime"):
            date = t["datetime"][:10]
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    return main.get_text("\n", strip=True), date


def _ensure_page(entry: dict) -> None:
    """Fetch the post page once; cache its text and (if missing) its date."""
    if "_page_text" not in entry:
        text, date = _page_text_and_date(_get(entry["link"]).text)
        entry["_page_text"] = text
        if not entry.get("published_date") and date:
            entry["published_date"] = date


def entry_issue_id(entry: dict) -> str:
    return entry["id"]


def entry_published_date(entry: dict) -> str:
    if not entry.get("published_date"):
        try:
            _ensure_page(entry)
        except Exception:
            pass
    return entry.get("published_date") or dt.date.today().isoformat()


def entry_text(entry: dict) -> str:
    raw = entry.get("_raw")
    if raw is not None:
        content = raw.get("content")
        if content and content[0].get("value") and len(content[0]["value"]) > 2000:
            return _html_to_text(content[0]["value"])
        summary = raw.get("summary", "")
        if len(summary) > 2000:
            return _html_to_text(summary)
    _ensure_page(entry)
    return entry["_page_text"]


def _html_to_text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
