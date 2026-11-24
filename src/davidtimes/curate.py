"""Pick which clusters a section features. LLM sees titles and snippets only."""

from __future__ import annotations

from davidtimes.config import Section
from davidtimes.llm import prompts
from davidtimes.llm.client import LLMClient
from davidtimes.llm.schemas import CurateOut
from davidtimes.models import Cluster

MAX_CANDIDATES = 40  # keeps the curation prompt small for free tiers


def fallback(clusters: list[Cluster], count: int) -> list[Cluster]:
    """No-LLM choice: clusters are already sorted by outlet coverage, then recency."""
    return clusters[:count]


async def curate(
    llm: LLMClient, section: Section, clusters: list[Cluster], count: int, recap: str | None
) -> list[Cluster]:
    candidates = clusters[:MAX_CANDIDATES]
    if not candidates:
        return []
    digest = [
        prompts.cluster_digest(c.id, c.outlets, c.lead.title, c.lead.summary or c.lead.content)
        for c in candidates
    ]
    out = await llm.json(
        "curate",
        prompts.CURATE_SYSTEM,
        prompts.curate_user(section.name, digest, count, recap),
        CurateOut,
    )
    by_id = {c.id: c for c in candidates}
    chosen = dict.fromkeys(s.cluster_id for s in out.selected if s.cluster_id in by_id)
    return [by_id[cid] for cid in chosen][:count]
