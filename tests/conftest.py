from datetime import UTC, datetime
from pathlib import Path

import pytest

from davidtimes.models import Item, Piece

FIXTURES = Path(__file__).parent / "fixtures"


def make_item(title: str, url: str, source: str = "A", content: str = "", hours_ago: int = 1) -> Item:
    return Item(section="f1", source=source, title=title, url=url, content=content,
                published=datetime(2026, 11, 24, 12, tzinfo=UTC).replace(hour=12 - hours_ago))


def make_piece(section: str, rank: int, words: int) -> Piece:
    return Piece(section=section, cluster_id=f"c{rank}", rank=rank, headline="H",
                 standfirst="", paragraphs=[" ".join(["palabra"] * (words - 1))], sources=[])


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
