"""RSS/Atom fetcher and feed autodiscovery."""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from urllib.parse import urljoin

import feedparser
import httpx
from lxml import html as lxml_html

from davidtimes.config import Section, Source
from davidtimes.extract import html_to_text
from davidtimes.fetch import FetchContext
from davidtimes.models import FetchResult, Item

FEED_TYPES = {"application/rss+xml", "application/atom+xml", "application/feed+json"}


def _entry_date(entry: feedparser.FeedParserDict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)


def parse_feed(data: bytes, source: Source, section: Section) -> list[Item]:
    """Parse feed bytes into Items (no date filter)."""
    feed = feedparser.parse(data)
    if feed.bozo and not feed.entries:
        raise ValueError(f"unparseable feed: {feed.bozo_exception}")
    items = []
    for entry in feed.entries:
        link, title = entry.get("link"), entry.get("title")
        if not link or not title:
            continue
        content = ""
        if entry.get("content"):
            content = html_to_text(entry.content[0].get("value", ""))
        items.append(
            Item(
                section=section.id,
                source=source.name,
                title=html_to_text(title),
                url=link,
                published=_entry_date(entry),
                summary=html_to_text(entry.get("summary", ""))[:600],
                content=content,
            )
        )
    return items


async def fetch(
    client: httpx.AsyncClient, source: Source, section: Section, ctx: FetchContext
) -> FetchResult:
    resp = await client.get(source.param("url"))
    resp.raise_for_status()
    items = parse_feed(resp.content, source, section)
    # Undated items are kept: some feeds omit dates, and dedupe/curation handle noise.
    recent = [i for i in items if i.published is None or i.published >= ctx.since]
    return FetchResult(source=source.name, items=recent)


def discover_feeds(page_html: str, base_url: str) -> list[str]:
    """Return feed URLs announced by <link rel="alternate"> on a page."""
    try:
        doc = lxml_html.fromstring(page_html)
    except Exception:
        return []
    found = []
    for link in doc.xpath('//link[contains(@rel, "alternate")]'):
        if (link.get("type") or "").lower() in FEED_TYPES and link.get("href"):
            found.append(urljoin(base_url, link.get("href")))
    return list(dict.fromkeys(found))
