import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from davidtimes.cache import Cache
from davidtimes.config import LLMConfig, Provider, load_llm, load_sources
from davidtimes.llm.client import LLMClient, LLMError, parse_json
from davidtimes.llm.schemas import CurateOut, SynthOut


def test_parse_json_tolerates_fences_and_prose():
    out = parse_json('Sure!\n```json\n{"selected": [{"cluster_id": "c1", "reason": "big"}]}\n```',
                     CurateOut)
    assert out.selected[0].cluster_id == "c1"


def test_parse_json_rejects_bad_shapes():
    with pytest.raises(ValidationError):
        parse_json('{"selected": [{"cluster_id": "c1"}]}', CurateOut)
    with pytest.raises(ValueError):
        parse_json("no json here", SynthOut)


def test_shipped_configs_validate():
    sources = load_sources()
    assert {s.id for s in sources.sections} >= {"f1", "premier-league", "cultura"}
    assert all(src.type for s in sources.sections for src in s.sources)
    assert load_llm().providers[0].name == "gemini"


class FakeCompletions:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    async def create(self, **_):
        self.calls += 1
        msg = SimpleNamespace(content=self.replies.pop(0))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


def _client(tmp_path, monkeypatch, replies):
    monkeypatch.setenv("FAKE_KEY", "x")
    cfg = LLMConfig(requests_per_minute=6000, providers=[
        Provider(name="fake", base_url="http://x", api_key_env="FAKE_KEY", models={"curate": "m"})])
    fake = FakeCompletions(replies)
    factory = lambda p, t: SimpleNamespace(chat=SimpleNamespace(completions=fake))  # noqa: E731
    return LLMClient(cfg, Cache(tmp_path / "c.sqlite"), factory=factory), fake


def test_client_retries_once_with_validation_error_then_caches(tmp_path, monkeypatch):
    good = '{"selected": [{"cluster_id": "c2", "reason": "ok"}]}'
    llm, fake = _client(tmp_path, monkeypatch, ['{"selected": "nope"}', good])
    out = asyncio.run(llm.json("curate", "sys", "user", CurateOut))
    assert out.selected[0].cluster_id == "c2" and fake.calls == 2
    again = asyncio.run(llm.json("curate", "sys", "user", CurateOut))
    assert again == out and fake.calls == 2 and llm.stats.cache_hits == 1


def test_client_offline_without_cache_raises(tmp_path, monkeypatch):
    llm, _ = _client(tmp_path, monkeypatch, [])
    llm.offline = True
    with pytest.raises(LLMError):
        asyncio.run(llm.json("curate", "sys", "user", CurateOut))
