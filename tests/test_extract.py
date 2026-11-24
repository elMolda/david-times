from datetime import UTC, datetime

from davidtimes.config import Section, Source
from davidtimes.extract import clean_text, html_to_text, looks_paywalled, truncate
from davidtimes.fetch.rss import discover_feeds, parse_feed


def test_html_to_text_keeps_paragraphs_and_drops_boilerplate():
    html = "<p>Uno &amp; dos.</p><p>Publicidad</p><div>Tres&nbsp; cuatro</div><p>Lea también: otra</p>"
    assert html_to_text(html) == "Uno & dos.\n\nTres cuatro"


def test_clean_text_collapses_whitespace():
    assert clean_text("  a   b \n\n\n c\t\td  ") == "a b\n\nc d"


def test_paywall_detection():
    long = "palabra " * 200
    assert looks_paywalled("too short", 600)
    assert looks_paywalled(long + " Suscríbete para seguir leyendo", 600)
    assert not looks_paywalled(long, 600)


def test_truncate_cuts_on_word_boundary():
    assert truncate("alpha beta gamma", 12) == "alpha beta […]"
    assert truncate("short", 100) == "short"


def test_parse_feed_fixture(fixtures):
    section = Section(id="f1", name="F1", sources=[])
    items = parse_feed((fixtures / "feed.xml").read_bytes(), Source(type="rss", name="Fix"), section)
    assert [i.title for i in items] == ["Verstappen wins & extends lead", "Old story"]
    first = items[0]
    assert first.published == datetime(2026, 11, 23, 22, tzinfo=UTC)
    assert first.content == "First paragraph of the full body.\n\nSecond paragraph."
    assert first.summary == "Short teaser."


def test_discover_feeds(fixtures):
    found = discover_feeds((fixtures / "home.html").read_text(), "https://www.example.co/")
    assert found == ["https://www.example.co/rss/economia", "https://cdn.example.com/atom.xml"]
