import asyncio
import json

from conftest import make_item
from test_schemas import _client

from davidtimes.config import Section, Settings
from davidtimes.curate import curate
from davidtimes.dedupe import cluster_items
from davidtimes.synthesize import Material, write_section

SECTION = Section(id="f1", name="F1", sources=[])


def _piece(cid: str, words: int, skip: bool = False) -> dict:
    return {"cluster_id": cid, "skip": skip, "headline": "Titular", "standfirst": "Entrada",
            "paragraphs": [" ".join(["texto"] * words)]}


def test_curate_keeps_known_ids_in_order(tmp_path, monkeypatch):
    clusters = cluster_items([make_item("Alpha story here now", "https://a.com/1"),
                              make_item("Beta other thing entirely", "https://b.com/2")])
    reply = {"selected": [{"cluster_id": "c2", "reason": "r"}, {"cluster_id": "c9", "reason": "x"},
                          {"cluster_id": "c2", "reason": "dup"}]}
    llm, _ = _client(tmp_path, monkeypatch, [json.dumps(reply)])
    chosen = asyncio.run(curate(llm, SECTION, clusters, 3, None))
    assert [c.id for c in chosen] == ["c2"]


def test_write_section_skips_and_rewrites_off_target(tmp_path, monkeypatch):
    mats = [Material(c, [(c.lead, "text")]) for c in cluster_items([
        make_item("Alpha story here now", "https://a.com/1", "A"),
        make_item("Beta other thing entirely", "https://b.com/2", "B"),
        make_item("Gamma third topic today", "https://c.com/3", "C"),
    ])]
    batch = {"pieces": [_piece("c1", 400), _piece("c2", 100), _piece("c3", 0, skip=True)]}
    rewrite = {"pieces": [_piece("c2", 390)]}
    llm, fake = _client(tmp_path, monkeypatch, [json.dumps(batch), json.dumps(rewrite)])
    llm.cfg.providers[0].models["synthesize"] = "m"
    pieces = asyncio.run(write_section(llm, SECTION, mats, 400, 500, None, Settings()))
    assert [p.cluster_id for p in pieces] == ["c1", "c2"]
    assert fake.calls == 2  # one batch call + one rewrite for the 100-word piece
    assert 380 < pieces[1].words < 420
    assert pieces[0].sources == [("A", "https://a.com/1")]  # sources come from data, not the LLM
