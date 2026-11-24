"""Jinja2 -> static HTML. Relative links only, no JS, one inlined CSS block."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from davidtimes.budget import reading_minutes
from davidtimes.config import TEMPLATES_DIR
from davidtimes.models import Block, Edition, Piece, SectionEdition

MONTHS = {
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
    "en": "January February March April May June July August September October November December",
}
DAYS = {
    "es": "lunes martes miércoles jueves viernes sábado domingo",
    "en": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday",
}
TEXT = {
    "es": {"index": "Índice", "next": "Siguiente", "prev": "Anterior", "min": "min de lectura",
           "about": "Unos {m} min de lectura", "target": "objetivo {m} min",
           "sources": "Fuentes", "data": "Datos", "archive": "Ediciones anteriores",
           "recap": "Sin evento en las últimas horas: repaso y previa.",
           "empty": "Hoy no hay material suficiente para esta sección."},
    "en": {"index": "Index", "next": "Next", "prev": "Previous", "min": "min read",
           "about": "About {m} min read", "target": "target {m} min",
           "sources": "Sources", "data": "Data", "archive": "Past editions",
           "recap": "No event in the window: recap and preview.",
           "empty": "Not enough material for this section today."},
}
EDITION_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class Page:
    file: str
    title: str
    section: SectionEdition
    piece: Piece | None = None
    blocks: list[Block] = field(default_factory=list)
    minutes: int = 0


def long_date(d, lang: str) -> str:
    day, month = DAYS[lang].split()[d.weekday()], MONTHS[lang].split()[d.month - 1]
    return f"{day} {d.day} de {month} de {d.year}" if lang == "es" else f"{day} {d.day} {month} {d.year}"


def build_pages(edition: Edition) -> list[Page]:
    pages = []
    wpm = edition.words_per_minute
    for section in edition.sections:
        for n, piece in enumerate(section.pieces, 1):
            pages.append(Page(f"{section.id}-{n}.html", piece.headline, section, piece=piece,
                              minutes=reading_minutes(piece.words, wpm)))
        if section.blocks:
            title = TEXT[section.language]["data"] + ": " + section.name
            pages.append(Page(f"{section.id}-datos.html", title, section, blocks=section.blocks))
    return pages


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape(),
                      trim_blocks=True, lstrip_blocks=True)
    env.globals["css"] = (TEMPLATES_DIR / "style.css").read_text(encoding="utf-8")
    env.globals["TEXT"] = TEXT
    return env


def list_editions(dist: Path) -> list[str]:
    return sorted((p.name for p in dist.iterdir()
                   if p.is_dir() and EDITION_DIR.match(p.name) and (p / "index.html").exists()),
                  reverse=True)


def render_edition(edition: Edition, dist: Path) -> Path:
    """Write dist/<date>/*.html, dist/index.html (latest) and dist/archive.html."""
    env = _env()
    out = dist / edition.date.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    pages = build_pages(edition)
    t = TEXT[edition.language]
    wpm = edition.words_per_minute
    front_ctx = {
        "edition": edition, "pages": pages, "t": t, "lang": edition.language,
        "date_text": long_date(edition.date, edition.language),
        "total_minutes": reading_minutes(edition.words, wpm),
        "section_minutes": {s.id: reading_minutes(s.words, wpm) for s in edition.sections},
    }
    for old in out.glob("*.html"):  # a rebuild may have fewer pages
        old.unlink()
    (out / "index.html").write_text(
        env.get_template("front.html").render(**front_ctx, prefix="", root="../"), "utf-8")
    article = env.get_template("article.html")
    for i, page in enumerate(pages):
        nxt = pages[i + 1].file if i + 1 < len(pages) else "index.html"
        html = article.render(page=page, next=nxt, t=TEXT[page.section.language],
                              lang=page.section.language, edition=edition)
        (out / page.file).write_text(html, "utf-8")

    if edition.date.isoformat() == max(list_editions(dist)):
        (dist / "index.html").write_text(
            env.get_template("front.html").render(
                **front_ctx, prefix=f"{edition.date.isoformat()}/", root=""), "utf-8")
    (dist / "archive.html").write_text(
        env.get_template("archive.html").render(editions=list_editions(dist), t=t,
                                                lang=edition.language), "utf-8")
    return out
