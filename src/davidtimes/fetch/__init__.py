"""Source fetchers. Each type maps to one async function; add new types to FETCHERS."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

import httpx

from davidtimes.config import Section, Settings, Source
from davidtimes.models import FetchResult

log = logging.getLogger(__name__)


@dataclass
class FetchContext:
    since: datetime  # aware UTC
    now: datetime  # aware UTC
    settings: Settings


Fetcher = Callable[
    [httpx.AsyncClient, Source, Section, FetchContext], Awaitable[FetchResult]
]


def redact(text: str) -> str:
    """Hide API keys that httpx error messages echo from query strings."""
    return re.sub(r"(api[-_]?key|token|key)=[^&\s'\"]+", r"\1=***", text, flags=re.I)


class SkipSource(Exception):
    """Raised when a source cannot run by design (e.g. no API key)."""


def _registry() -> dict[str, Fetcher]:
    from davidtimes.fetch import datosgov, footballdata, guardian, jolpica, rss

    return {
        "rss": rss.fetch,
        "guardian_api": guardian.fetch,
        "jolpica": jolpica.fetch,
        "football_data": footballdata.fetch,
        "datos_gov_trm": datosgov.fetch,
    }


def make_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent},
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=10),
    )


async def fetch_source(
    client: httpx.AsyncClient, source: Source, section: Section, ctx: FetchContext
) -> FetchResult:
    """Run one source. Never raises: failures become ok=False results."""
    fetcher = _registry().get(source.type)
    if fetcher is None:
        return FetchResult(source=source.name, ok=False, error=f"unknown type {source.type!r}")
    try:
        return await asyncio.wait_for(fetcher(client, source, section, ctx), timeout=45)
    except SkipSource as exc:
        log.info("skip %s: %s", source.name, exc)
        return FetchResult(source=source.name, skipped=True, error=str(exc))
    except Exception as exc:  # a failing source must never crash the run
        msg = redact(f"{type(exc).__name__}: {exc}")[:200]
        log.warning("source failed %s: %s", source.name, msg)
        return FetchResult(source=source.name, ok=False, error=msg)
