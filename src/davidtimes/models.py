"""Data passed between pipeline stages."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class Item(BaseModel):
    section: str
    source: str
    title: str
    url: str
    published: datetime | None = None
    summary: str = ""
    content: str = ""  # full text when the feed/API already gives it


class Block(BaseModel):
    """A table of numbers that comes straight from an API. The LLM never touches it."""

    title: str
    columns: list[str]
    rows: list[list[str]]
    note: str = ""


class FetchResult(BaseModel):
    source: str
    ok: bool = True
    skipped: bool = False
    error: str = ""
    items: list[Item] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    # Structured sources say whether a race/matchday fell in the window (None = unknown).
    event_in_window: bool | None = None


class Cluster(BaseModel):
    id: str
    items: list[Item]

    @property
    def lead(self) -> Item:
        return self.items[0]

    @property
    def outlets(self) -> list[str]:
        return list(dict.fromkeys(i.source for i in self.items))


class Piece(BaseModel):
    section: str
    cluster_id: str
    rank: int
    headline: str
    standfirst: str
    paragraphs: list[str]
    sources: list[tuple[str, str]]  # (outlet, url)

    @property
    def words(self) -> int:
        from davidtimes.budget import count_words

        return count_words(" ".join([self.headline, self.standfirst, *self.paragraphs]))


class SectionEdition(BaseModel):
    id: str
    name: str
    language: str
    pieces: list[Piece] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    recap: bool = False
    budget_words: int = 0
    note: str = ""  # e.g. "little material today"

    @property
    def words(self) -> int:
        return sum(p.words for p in self.pieces)


class Edition(BaseModel):
    date: date
    language: str = "es"
    words_per_minute: int = 220
    target_minutes: int = 30
    sections: list[SectionEdition] = Field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(s.words for s in self.sections)
