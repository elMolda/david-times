import re
from datetime import date

from davidtimes.models import Block, Edition, Piece, SectionEdition
from davidtimes.render import render_edition


def _edition(day: date) -> Edition:
    piece = Piece(section="f1", cluster_id="c1", rank=0, headline="Verstappen <gana>",
                  standfirst="Entrada.", paragraphs=["Uno dos tres."] * 3,
                  sources=[("BBC", "https://bbc.co.uk/x")])
    f1 = SectionEdition(id="f1", name="Fórmula 1", language="es", pieces=[piece],
                        blocks=[Block(title="Tabla", columns=["Pos", "Piloto"], rows=[["1", "M. V"]])])
    culture = SectionEdition(id="culture", name="Culture", language="en", pieces=[
        piece.model_copy(update={"section": "culture", "headline": "Books"})])
    return Edition(date=day, sections=[f1, culture])


def test_render_writes_linked_static_pages(tmp_path):
    out = render_edition(_edition(date(2026, 11, 24)), tmp_path)
    files = sorted(p.name for p in out.iterdir())
    assert files == ["culture-1.html", "f1-1.html", "f1-datos.html", "index.html"]

    all_html = {p: p.read_text() for p in tmp_path.rglob("*.html")}
    for path, html in all_html.items():
        assert "<script" not in html and "<img" not in html and "@import" not in html
        assert html.startswith("<!DOCTYPE html>")
        for href in re.findall(r'href="([^"]+)"', html):
            if href.startswith("http"):
                continue  # only source links in the article footer
            assert not href.startswith("/"), href
            assert (path.parent / href).resolve().exists(), (path, href)

    front = (out / "index.html").read_text()
    assert "martes 24 de noviembre de 2026" in front
    assert "Verstappen &lt;gana&gt;" in front  # autoescaped
    article = (out / "f1-1.html").read_text()
    assert article.count("← Índice") == 2 and article.count('href="f1-datos.html"') == 2
    assert '<html lang="en">' in (out / "culture-1.html").read_text()
    assert 'href="2026-11-24/f1-1.html"' in (tmp_path / "index.html").read_text()


def test_root_index_points_to_latest_and_archive_lists_all(tmp_path):
    render_edition(_edition(date(2026, 11, 24)), tmp_path)
    render_edition(_edition(date(2026, 11, 20)), tmp_path)  # older rebuild must not take over
    assert "2026-11-24/" in (tmp_path / "index.html").read_text()
    archive = (tmp_path / "archive.html").read_text()
    assert archive.index("2026-11-24") < archive.index("2026-11-20")
