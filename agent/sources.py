"""Newsletter source adapters.

Each adapter's `discover(since, until)` returns normalized entries (oldest-first):
    {id, link, published_date, source, _raw}
which then flow through the same extract -> record pipeline. Adding a newsletter
means adding an adapter here; nothing downstream changes.

StrictlyVC reuses the feed/homepage logic in ingest.py. Pro Rata and Term Sheet
crawl a listing/archive page for date-pathed article links (both axios.com and
fortune.com put the date in the URL as /YYYY/MM/DD/slug, so we read the date
straight from the link and only fetch pages within range).

NOTE: the Pro Rata and Term Sheet adapters are best-effort and expected to need
first-run tuning against the live HTML (archive URL + which links to keep) — which
is exactly why we validate on a short window before backfilling the year.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from . import config, ingest

_DATE_PATH = re.compile(r"/(20\d{2})/(\d{2})/(\d{2})/[a-z0-9][a-z0-9\-]*")


def _date_from_url(url: str) -> str:
    m = _DATE_PATH.search(url)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


class Source:
    name = "base"

    def discover(self, since=None, until=None) -> list[dict]:
        raise NotImplementedError


class StrictlyVCSource(Source):
    name = "strictlyvc"

    def discover(self, since=None, until=None):
        return ingest.strictlyvc_entries(since, until)


class ArchiveSource(Source):
    """Crawl a listing page for date-pathed article links (axios.com / fortune.com)."""
    ARCHIVE_URL = ""
    BASE = ""
    MAX_PAGES = 8  # listing pages to walk when backfilling

    def _listing_urls(self):
        yield self.ARCHIVE_URL
        for p in range(2, self.MAX_PAGES + 1):
            sep = "&" if "?" in self.ARCHIVE_URL else "?"
            yield f"{self.ARCHIVE_URL}{sep}page={p}"

    def discover(self, since=None, until=None):
        seen, entries = set(), []
        for listing in self._listing_urls():
            try:
                html = ingest._get(listing).text
            except Exception:
                break
            page_dates = []
            for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
                date = _date_from_url(a["href"])
                if not date:
                    continue
                page_dates.append(date)
                url = a["href"]
                if not url.startswith("http"):
                    url = self.BASE.rstrip("/") + "/" + url.lstrip("/")
                url = url.split("?")[0].split("#")[0]
                if url in seen:
                    continue
                if (since and date < since) or (until and date > until):
                    continue
                seen.add(url)
                entries.append({"id": url, "link": url, "published_date": date,
                                "source": self.name, "_raw": None})
            # Once a whole listing page predates `since`, older pages will too.
            if since and page_dates and max(page_dates) < since:
                break
            if not page_dates:  # no dated links here -> nothing more to page through
                break
        entries.sort(key=lambda e: e["published_date"])
        return entries


class ProRataSource(ArchiveSource):
    name = "prorata"
    ARCHIVE_URL = config.PRORATA_ARCHIVE_URL
    BASE = "https://www.axios.com"


class TermSheetSource(ArchiveSource):
    name = "termsheet"
    ARCHIVE_URL = config.TERMSHEET_ARCHIVE_URL
    BASE = "https://fortune.com"


SOURCES = {s.name: s for s in (StrictlyVCSource(), ProRataSource(), TermSheetSource())}


def collect_entries(names, since=None, until=None) -> list[dict]:
    """Gather entries from the named sources, merged and sorted oldest-first."""
    out = []
    for n in names:
        src = SOURCES.get(n)
        if not src:
            print(f"[source] unknown source '{n}' — skipping")
            continue
        try:
            found = src.discover(since, until)
            print(f"[source] {n}: {len(found)} issue(s)")
            out += found
        except Exception as e:  # noqa: BLE001
            print(f"[source] {n} discovery failed: {type(e).__name__}: {e}")
    out.sort(key=lambda e: e.get("published_date") or "")
    return out
