"""Article text: HTML cleanup, paywall heuristics, page extraction with trafilatura."""

from __future__ import annotations

import asyncio
import html
import logging
import re

import httpx
import trafilatura

from davidtimes.cache import Cache
from davidtimes.models import Item

log = logging.getLogger(__name__)

_BLOCK_TAGS = re.compile(r"</?(p|div|br|li|h[1-6]|blockquote|tr)[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_BOILERPLATE = re.compile(
    r"^(advertisement|publicidad|read more|leer más|lea también|sign up|"
    r"subscribe|suscríbete|share this|compartir|related:|relacionado:|"
    r"follow us|síguenos|the post .* appeared first on).*$",
    re.I,
)
_PAYWALL = re.compile(
    r"(subscribe to (continue|read)|already a subscriber|this article is for subscribers|"
    r"contenido exclusivo para suscriptores|suscríbete para (seguir|continuar) leyendo|"
    r"para continuar leyendo|hazte suscriptor|exclusive to members)",
    re.I,
)


def html_to_text(raw: str) -> str:
    """Turn an HTML fragment into plain text with paragraph breaks."""
    if not raw:
        return ""
    text = _BLOCK_TAGS.sub("\n", raw)
    text = html.unescape(_TAGS.sub("", text))
    return clean_text(text)


def clean_text(text: str) -> str:
    """Collapse whitespace and drop boilerplate lines; keep paragraph breaks."""
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t ]+", " ", line).strip()
        if line and not _BOILERPLATE.match(line):
            lines.append(line)
    return "\n\n".join(lines)


def looks_paywalled(text: str, min_chars: int) -> bool:
    return len(text) < min_chars or bool(_PAYWALL.search(text[-1500:]))


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut + " […]"


async def _fetch_page_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url)
    resp.raise_for_status()
    extracted = await asyncio.to_thread(
        trafilatura.extract, resp.text, include_comments=False, include_tables=False
    )
    return clean_text(extracted or "")


async def full_text(
    client: httpx.AsyncClient | None, item: Item, cache: Cache, min_chars: int, offline: bool
) -> str | None:
    """Best available full text for an item, or None if paywalled / too thin."""
    text = item.content
    if len(text) < min_chars:
        cached = cache.get("extract", item.url)
        if cached is not None:
            text = cached
        elif not offline and client is not None:
            try:
                text = await _fetch_page_text(client, item.url)
            except httpx.HTTPStatusError as exc:
                log.info("extract: HTTP %s for %s", exc.response.status_code, item.url[:100])
                text = ""
            except Exception as exc:
                log.info("extract: %s for %s", type(exc).__name__, item.url[:100])
                text = ""
            cache.set("extract", item.url, text)
    if looks_paywalled(text, min_chars):
        return None
    return text
