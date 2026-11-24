"""Turn selected clusters into finished pieces (LLM) or raw pieces (--no-llm)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from davidtimes import budget
from davidtimes.cache import Cache
from davidtimes.config import Section, Settings
from davidtimes.extract import full_text
from davidtimes.llm import prompts
from davidtimes.llm.client import LLMClient
from davidtimes.llm.schemas import PieceOut, SynthOut
from davidtimes.models import Cluster, Item, Piece

log = logging.getLogger(__name__)


@dataclass
class Material:
    cluster: Cluster
    texts: list[tuple[Item, str]]  # only items with usable full text

    def sources(self) -> list[tuple[str, str]]:
        return [(item.source, item.url) for item, _ in self.texts]


async def gather(
    client: httpx.AsyncClient | None,
    clusters: list[Cluster],
    cache: Cache,
    settings: Settings,
    offline: bool,
) -> list[Material]:
    """Full text for each cluster; clusters with no usable text are dropped."""

    async def one(cluster: Cluster) -> Material:
        items = cluster.items[: settings.max_sources_per_cluster]
        texts = await asyncio.gather(
            *(full_text(client, i, cache, settings.min_article_chars, offline) for i in items)
        )
        return Material(cluster, [(i, t) for i, t in zip(items, texts, strict=True) if t])

    materials = await asyncio.gather(*(one(c) for c in clusters))
    return [m for m in materials if m.texts]


def raw_piece(section: str, rank: int, m: Material, target: int) -> Piece:
    """--no-llm: the lead source's own text, cut to the word target."""
    lead, text = m.texts[0]
    paragraphs, words = [], 0
    for para in text.split("\n\n"):
        if words >= target:
            break
        paragraphs.append(para)
        words += budget.count_words(para)
    return Piece(
        section=section, cluster_id=m.cluster.id, rank=rank, headline=lead.title,
        standfirst=lead.summary[:300], paragraphs=paragraphs, sources=m.sources(),
    )


def _to_piece(section: str, rank: int, m: Material, out: PieceOut) -> Piece | None:
    if out.skip or not out.paragraphs:
        log.info("LLM skipped %s: %s", m.cluster.id, out.skip_reason)
        return None
    return Piece(
        section=section, cluster_id=m.cluster.id, rank=rank, headline=out.headline,
        standfirst=out.standfirst, paragraphs=[p for p in out.paragraphs if p.strip()],
        sources=m.sources(),
    )


async def write_section(
    llm: LLMClient,
    section: Section,
    materials: list[Material],
    target: int,
    hard_max: int,
    recap: str | None,
    settings: Settings,
    first_rank: int = 0,
) -> list[Piece]:
    """One batched call for all pieces of a section, then one rewrite per off-target piece."""
    if not materials:
        return []
    payload = [
        prompts.material(m.cluster.id, [(i.source, i.title, t) for i, t in m.texts],
                         settings.max_article_chars)
        for m in materials
    ]
    out = await llm.json(
        "synthesize", prompts.SYNTH_SYSTEM,
        prompts.synth_user(section.name, section.language, payload, target, hard_max, recap),
        SynthOut,
    )
    by_id = {p.cluster_id: p for p in out.pieces}
    pieces = []
    for rank, m in enumerate(materials, first_rank):
        if m.cluster.id not in by_id:
            continue
        piece_out = by_id[m.cluster.id]
        piece = _to_piece(section.id, rank, m, piece_out)
        if piece and budget.off_target(piece.words, target):
            piece = await _rewrite(llm, section, m, piece_out, piece, target, hard_max, rank)
        if piece:
            pieces.append(piece)
    return pieces


async def _rewrite(
    llm: LLMClient, section: Section, m: Material, out: PieceOut, piece: Piece,
    target: int, hard_max: int, rank: int,
) -> Piece:
    log.info("piece %s/%s has %d words (target %d): rewriting once",
             section.id, m.cluster.id, piece.words, target)
    try:
        again = await llm.json(
            "synthesize", prompts.SYNTH_SYSTEM,
            prompts.rewrite_user(out.model_dump(), piece.words, target, hard_max), SynthOut,
        )
    except Exception as exc:  # keep the first version rather than losing the piece
        log.warning("rewrite failed for %s: %s", m.cluster.id, exc)
        return piece
    if not again.pieces:
        return piece
    better = _to_piece(section.id, rank, m, again.pieces[0])
    if better and abs(better.words - target) < abs(piece.words - target):
        return better
    return piece
