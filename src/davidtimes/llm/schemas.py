"""JSON shapes the LLM must return. Validated with pydantic."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CurateChoice(BaseModel):
    cluster_id: str
    reason: str


class CurateOut(BaseModel):
    selected: list[CurateChoice]


class PieceOut(BaseModel):
    cluster_id: str
    skip: bool = False
    skip_reason: str = ""
    headline: str = ""
    standfirst: str = ""
    paragraphs: list[str] = Field(default_factory=list)


class SynthOut(BaseModel):
    pieces: list[PieceOut]
