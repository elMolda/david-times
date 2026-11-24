"""Guardian Open Platform: returns the full article body, so it beats scraping."""

from __future__ import annotations

import os
from datetime import datetime

import httpx

from davidtimes.config import Section, Source
from davidtimes.extract import html_to_text
from davidtimes.fetch import FetchContext, SkipSource
from davidtimes.models import FetchResult, Item

API = "https://content.guardianapis.com/search"


async def fetch(
    client: httpx.AsyncClient, source: Source, section: Section, ctx: FetchContext
) -> FetchResult:
    key = os.environ.get("GUARDIAN_API_KEY")
    if not key:
        raise SkipSource("GUARDIAN_API_KEY not set")
    params = {
        "api-key": key,
        "from-date": ctx.since.date().isoformat(),
        "order-by": "newest",
        "page-size": "30",
        "show-fields": "bodyText,trailText",
        "type": "article",
    }
    for opt in ("tag", "section", "q"):
        if source.param(opt):
            params[opt] = source.param(opt)
    resp = await client.get(API, params=params)
    resp.raise_for_status()
    items = []
    for r in resp.json()["response"]["results"]:
        published = datetime.fromisoformat(r["webPublicationDate"].replace("Z", "+00:00"))
        if published < ctx.since:
            continue
        fields = r.get("fields", {})
        items.append(
            Item(
                section=section.id,
                source="The Guardian",
                title=r["webTitle"],
                url=r["webUrl"],
                published=published,
                summary=html_to_text(fields.get("trailText", "")),
                content=fields.get("bodyText", ""),
            )
        )
    return FetchResult(source=source.name, items=items)
