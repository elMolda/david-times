"""`check-sources`: validate every source and suggest feed URLs for broken RSS ones."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx

from davidtimes.config import Section, Source, load_sources
from davidtimes.fetch import FetchContext, fetch_source, make_client
from davidtimes.fetch.rss import discover_feeds, parse_feed


@dataclass
class Row:
    section: str
    source: str
    status: str  # HTTP code, OK, SKIP, FAIL
    parsed: int
    recent: int
    latest: str
    note: str = ""


async def _discover(client: httpx.AsyncClient, url: str) -> list[str]:
    parts = urlsplit(url)
    try:
        resp = await client.get(f"{parts.scheme}://{parts.netloc}/")
        return discover_feeds(resp.text, str(resp.url))
    except httpx.HTTPError:
        return []


async def check_rss(client: httpx.AsyncClient, source: Source, section: Section,
                    since: datetime) -> Row:
    url = source.param("url")
    row = Row(section.id, source.name, "FAIL", 0, 0, "-")
    try:
        resp = await client.get(url)
        row.status = str(resp.status_code)
        if resp.is_success:
            items = parse_feed(resp.content, source, section)
            dated = [i.published for i in items if i.published]
            row.parsed = len(items)
            row.recent = sum(1 for d in dated if d >= since)
            row.latest = max(dated).strftime("%Y-%m-%d %H:%M") if dated else "-"
    except Exception as exc:
        row.note = f"{type(exc).__name__}: {exc}"[:80]
    if row.parsed == 0:
        found = await _discover(client, url)
        row.note = (row.note + " | " if row.note else "") + (
            "try: " + ", ".join(found[:3]) if found else "no feed found by autodiscovery")
    return row


async def check_other(client: httpx.AsyncClient, source: Source, section: Section,
                      ctx: FetchContext) -> Row:
    result = await fetch_source(client, source, section, ctx)
    status = "SKIP" if result.skipped else "OK" if result.ok else "FAIL"
    return Row(section.id, source.name, status, len(result.items) + len(result.blocks),
               len(result.items), "-", result.error[:80] or f"{len(result.blocks)} data blocks")


async def run_checks() -> list[Row]:
    cfg = load_sources()
    now = datetime.now(UTC)
    since = now - timedelta(hours=cfg.settings.lookback_hours)
    ctx = FetchContext(since=since, now=now, settings=cfg.settings)
    async with make_client(cfg.settings) as client:
        jobs = [
            check_rss(client, src, sec, since) if src.type == "rss"
            else check_other(client, src, sec, ctx)
            for sec in cfg.sections for src in sec.sources if src.enabled
        ]
        return list(await asyncio.gather(*jobs))


def format_table(rows: list[Row], lookback: int = 36) -> str:
    head = ["SECTION", "SOURCE", "STATUS", "PARSED", f"LAST {lookback}H", "LATEST (UTC)", "NOTE"]
    data = [[r.section, r.source, r.status, str(r.parsed), str(r.recent), r.latest, r.note]
            for r in rows]
    widths = [max(len(x[i]) for x in [head, *data]) for i in range(len(head) - 1)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths) + "  {}"
    return "\n".join(fmt.format(*line) for line in [head, *data])


def is_bad(row: Row) -> bool:
    return row.status not in ("200", "OK", "SKIP") or (row.status == "200" and row.parsed == 0)


def check_sources() -> int:
    rows = asyncio.run(run_checks())
    print(format_table(rows, load_sources().settings.lookback_hours))
    bad = [r for r in rows if is_bad(r)]
    print(f"\n{len(rows) - len(bad)}/{len(rows)} sources usable "
          f"({sum(r.status == 'SKIP' for r in rows)} skipped for missing keys).")
    return 1 if bad else 0
