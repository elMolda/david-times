"""Word budget per section/piece and reading-time maths. Pure functions."""

from __future__ import annotations

import math
import re

from davidtimes.models import Piece

TOLERANCE = 0.25  # a piece more than 25% off target gets one rewrite
EDITION_TOLERANCE = 0.10
MIN_PIECE_WORDS, MAX_PIECE_WORDS = 200, 600


def count_words(text: str) -> int:
    return len(re.findall(r"\w+(?:[-'’]\w+)*", text))


def reading_minutes(words: int, wpm: int) -> int:
    return max(1, round(words / wpm)) if words else 0


def total_budget(minutes: int, wpm: int) -> int:
    return minutes * wpm


def section_budgets(total: int, weights: dict[str, float]) -> dict[str, int]:
    """Split the total word budget across sections proportionally to weight."""
    weight_sum = sum(weights.values()) or 1.0
    return {sid: round(total * w / weight_sum) for sid, w in weights.items()}


def pieces_for(budget: int, words_per_piece: int) -> int:
    return max(1, round(budget / words_per_piece)) if budget > 0 else 0


def piece_target(budget: int, pieces: int) -> tuple[int, int]:
    """(target words, hard max) for each piece of a section."""
    target = budget // max(1, pieces)
    target = min(MAX_PIECE_WORDS, max(MIN_PIECE_WORDS, target))
    return target, math.ceil(target * (1 + TOLERANCE))


def off_target(words: int, target: int) -> bool:
    return abs(words - target) > target * TOLERANCE


def trim_to_budget(pieces: list[Piece], budget: int) -> list[Piece]:
    """Drop the lowest-ranked pieces (never a section's last one) until within +10%."""
    kept = list(pieces)
    limit = budget * (1 + EDITION_TOLERANCE)
    while sum(p.words for p in kept) > limit:
        per_section: dict[str, int] = {}
        for p in kept:
            per_section[p.section] = per_section.get(p.section, 0) + 1
        droppable = [p for p in kept if per_section[p.section] > 1]
        if not droppable:
            break
        worst = max(droppable, key=lambda p: (p.rank, p.words))
        kept.remove(worst)
    return kept


def needs_more(total_words: int, budget: int) -> bool:
    return total_words < budget * (1 - EDITION_TOLERANCE)
