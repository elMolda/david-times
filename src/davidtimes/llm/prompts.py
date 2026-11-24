"""Prompt text. Inputs are serialized deterministically so the cache key is stable."""

from __future__ import annotations

import json

from davidtimes.extract import truncate

LANGUAGE = {
    "es": "natural, neutral Latin American Spanish",
    "en": "natural British English",
}

CURATE_SYSTEM = """You are the editor of a calm, high-quality personal daily newspaper.
You pick which stories to feature in one section. Prefer fewer, better stories:
substance over gossip, news over listicles, stories covered by several outlets.
Never pick two clusters about the same story. Answer with JSON only."""

SYNTH_SYSTEM = """You write pieces for a calm personal daily newspaper read on an e-ink Kindle.
Rules:
- Use ONLY facts present in the provided source texts. Never invent facts, quotes, numbers or dates.
- Neutral newspaper tone. No filler, no hype, no clichés, no "in conclusion".
- Write real reading content: context, what happened, why it matters, what comes next.
- Keep proper names and technical terms (drivers, teams, clubs, companies, institutions) as they are.
- Do not reproduce standings or results tables; those are printed separately from official data.
- If the sources are too thin or contradictory to write an honest piece, set "skip": true with a reason.
Answer with JSON only."""


def curate_user(
    section_name: str, clusters: list[dict], count: int, recap: str | None
) -> str:
    focus = f"\nSection mode today: {recap}\n" if recap else ""
    return (
        f"Section: {section_name}{focus}\n"
        f"Choose up to {count} clusters to feature, best first. "
        "Each cluster lists its outlets and a snippet.\n\n"
        f"Clusters:\n{json.dumps(clusters, ensure_ascii=False, indent=1)}\n\n"
        'Return: {"selected": [{"cluster_id": "c3", "reason": "one line"}]}'
    )


def cluster_digest(cluster_id: str, outlets: list[str], title: str, snippet: str) -> dict:
    return {"id": cluster_id, "outlets": outlets, "title": title, "snippet": snippet[:280]}


def synth_user(
    section_name: str,
    language: str,
    materials: list[dict],
    target: int,
    hard_max: int,
    recap: str | None,
) -> str:
    focus = f"\nSection mode today: {recap}\n" if recap else ""
    return (
        f"Section: {section_name}{focus}\n"
        f"Write one piece per cluster below, in {LANGUAGE[language]}, translating as needed.\n"
        f"Each piece: a headline, a one-sentence standfirst, and a body of about {target} words "
        f"(hard maximum {hard_max} words) split into short paragraphs.\n\n"
        f"Clusters with source texts:\n{json.dumps(materials, ensure_ascii=False, indent=1)}\n\n"
        'Return: {"pieces": [{"cluster_id": "c1", "skip": false, "skip_reason": "", '
        '"headline": "...", "standfirst": "...", "paragraphs": ["...", "..."]}]}'
    )


def rewrite_user(previous: dict, words: int, target: int, hard_max: int) -> str:
    direction = "too long: cut it" if words > target else "too short: develop it from the sources"
    return (
        f"Your piece for cluster {previous['cluster_id']} has {words} words; the target is "
        f"{target} (hard maximum {hard_max}). It is {direction}. Rewrite it to about {target} "
        "words, same rules, same facts only.\n\n"
        f"Previous piece:\n{json.dumps(previous, ensure_ascii=False)}\n\n"
        'Return: {"pieces": [ ...exactly one piece... ]}'
    )


def material(cluster_id: str, sources: list[tuple[str, str, str]], max_chars: int) -> dict:
    """sources = [(outlet, title, text)]"""
    return {
        "cluster_id": cluster_id,
        "sources": [
            {"outlet": o, "title": t, "text": truncate(x, max_chars)} for o, t, x in sources
        ],
    }
