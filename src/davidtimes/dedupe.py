"""Cluster the same story across sources: canonical URL first, then fuzzy title match."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from davidtimes.models import Cluster, Item

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|cmpid|at_|ito|ref$|src$)", re.I)
_STOP = set(
    "a an and the of to in on for at by with from is are was be as it its this that "
    "el la los las un una de del y en por para con que se su al es lo como más".split()
)


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("amp.")
    path = re.sub(r"/(amp|amp\.html)$", "", parts.path).rstrip("/") or "/"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    return urlunsplit(("https", host, path, query, ""))


def title_tokens(title: str) -> set[str]:
    norm = unicodedata.normalize("NFKD", title.lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", norm) if w not in _STOP and len(w) > 2}


def similar(a: set[str], b: set[str], threshold: float = 0.5) -> bool:
    if not a or not b:
        return False
    # Overlap over the smaller set: short headlines about the same story match.
    return len(a & b) / min(len(a), len(b)) >= threshold and len(a & b) >= 3


def _richest_first(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda i: len(i.content), reverse=True)


def cluster_items(items: list[Item], threshold: float = 0.5) -> list[Cluster]:
    """Group items; clusters covered by more outlets come first."""
    by_url: dict[str, list[Item]] = {}
    for item in items:
        by_url.setdefault(canonical_url(item.url), []).append(item)
    # Same URL from RSS and API: keep the one with the most text.
    unique = [_richest_first(group)[0] for group in by_url.values()]

    groups: list[tuple[set[str], list[Item]]] = []
    for item in unique:
        tokens = title_tokens(item.title)
        for group_tokens, members in groups:
            if similar(tokens, group_tokens, threshold):
                members.append(item)
                group_tokens |= tokens
                break
        else:
            groups.append((tokens, [item]))

    clusters = [Cluster(id="", items=_richest_first(members)) for _, members in groups]
    def newest(c: Cluster) -> float:
        return max((i.published.timestamp() for i in c.items if i.published), default=0.0)

    clusters.sort(key=lambda c: (len(c.outlets), newest(c)), reverse=True)
    for n, cluster in enumerate(clusters, 1):
        cluster.id = f"c{n}"
    return clusters
