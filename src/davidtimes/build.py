"""The `build` pipeline: fetch -> dedupe -> curate -> extract -> synthesize -> budget -> render."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from davidtimes import budget, curate, synthesize
from davidtimes.cache import Cache
from davidtimes.config import CACHE_DIR, DIST_DIR, Section, SourcesConfig, load_llm, load_sources
from davidtimes.dedupe import cluster_items
from davidtimes.fetch import FetchContext, fetch_source, make_client
from davidtimes.llm.client import LLMClient, LLMError
from davidtimes.models import Edition, FetchResult, SectionEdition
from davidtimes.render import render_edition

log = logging.getLogger(__name__)


@dataclass
class BuildOptions:
    day: date | None = None
    sections: list[str] = field(default_factory=list)
    no_llm: bool = False
    offline: bool = False
    force: bool = False
    max_pieces: int | None = None
    minutes: int | None = None


@dataclass
class Summary:
    sources_ok: int = 0
    sources_failed: list[str] = field(default_factory=list)
    sources_skipped: list[str] = field(default_factory=list)
    items: int = 0
    clusters: int = 0
    pieces: int = 0
    words: int = 0
    budget_words: int = 0
    minutes: int = 0
    target_minutes: int = 0
    llm_failures: list[str] = field(default_factory=list)
    output: Path | None = None
    blocks: int = 0
    llm: LLMClient | None = None


@dataclass
class Ctx:
    cfg: SourcesConfig
    opts: BuildOptions
    cache: Cache
    client: httpx.AsyncClient | None
    llm: LLMClient | None
    summary: Summary


def _window(cfg: SourcesConfig, day: date | None) -> tuple[date, datetime, datetime]:
    tz = ZoneInfo(cfg.settings.timezone)
    now = datetime.now(tz)
    if day and day != now.date():
        now = datetime.combine(day, datetime.max.time(), tz)
    edition_day = now.date()
    now = now.astimezone(UTC)
    return edition_day, now, now - timedelta(hours=cfg.settings.lookback_hours)


async def _fetch_section(ctx: Ctx, section: Section, fctx: FetchContext, day: date) -> list[FetchResult]:
    async def one(source) -> FetchResult:
        key = f"{day.isoformat()}:{section.id}:{source.name}"
        cached = None if ctx.opts.force else ctx.cache.get("fetch", key)
        if cached is not None:
            return FetchResult.model_validate(cached)
        if ctx.opts.offline or ctx.client is None:
            return FetchResult(source=source.name, ok=False, error="offline: not in cache")
        result = await fetch_source(ctx.client, source, section, fctx)
        if result.ok and not result.skipped:
            ctx.cache.set("fetch", key, result.model_dump(mode="json"))
        return result

    return list(await asyncio.gather(*(one(s) for s in section.sources if s.enabled)))


def _tally(summary: Summary, results: list[FetchResult]) -> None:
    for r in results:
        if r.skipped:
            summary.sources_skipped.append(f"{r.source} ({r.error})")
        elif r.ok:
            summary.sources_ok += 1
        else:
            summary.sources_failed.append(f"{r.source} ({r.error})")


async def _write(ctx: Ctx, section: Section, mats, target, hard, recap, rank0=0, raw=False):
    if raw or ctx.llm is None:
        return [synthesize.raw_piece(section.id, r, m, target) for r, m in enumerate(mats, rank0)]
    return await synthesize.write_section(ctx.llm, section, mats, target, hard, recap,
                                          ctx.cfg.settings, rank0)


async def build_section(
    ctx: Ctx, section: Section, results: list[FetchResult], words_budget: int
) -> tuple[SectionEdition, list[synthesize.Material], tuple[int, int, str | None]]:
    s = ctx.cfg.settings
    items = [i for r in results for i in r.items]
    events = [r.event_in_window for r in results if r.event_in_window is not None]
    recap = section.recap_mode if section.recap_mode and events and not any(events) else None
    clusters = cluster_items(items)
    ctx.summary.items += len(items)
    ctx.summary.clusters += len(clusters)

    n = budget.pieces_for(words_budget, s.words_per_piece)
    if ctx.opts.max_pieces:
        n = min(n, ctx.opts.max_pieces)
    target, hard = budget.piece_target(words_budget, n)
    want = n + s.extra_candidates

    raw = ctx.llm is None
    chosen = curate.fallback(clusters, want)
    if not raw:
        try:
            chosen = await curate.curate(ctx.llm, section, clusters, want, recap)
        except LLMError as exc:
            ctx.summary.llm_failures.append(f"{section.id} curate: {exc}")
            raw = True
    mats = await synthesize.gather(ctx.client, chosen, ctx.cache, s, ctx.opts.offline)
    if len(mats) < want:  # blocked/paywalled pages: refill from the next-best clusters
        seen = {c.id for c in chosen}
        rest = [c for c in clusters if c.id not in seen][: 3 * want]
        more = await synthesize.gather(ctx.client, rest, ctx.cache, s, ctx.opts.offline)
        mats += more[: want - len(mats)]
    use, spare = mats[:n], mats[n:]
    try:
        pieces = await _write(ctx, section, use, target, hard, recap, raw=raw)
        if len(pieces) < n and spare:  # the LLM skipped weak clusters: use spares
            extra, spare = spare[: n - len(pieces)], spare[n - len(pieces):]
            pieces += await _write(ctx, section, extra, target, hard, recap, len(use), raw)
    except LLMError as exc:
        ctx.summary.llm_failures.append(f"{section.id} synthesize: {exc}")
        raw = True
        pieces = await _write(ctx, section, use, target, hard, recap, raw=True)

    note = ""
    if raw and ctx.llm is not None:
        note = "LLM no disponible: texto original sin editar." if section.language == "es" \
            else "LLM unavailable: unedited source text."
    elif len(pieces) < n:
        note = (f"Hoy hubo poco material: {len(pieces)} de {n} piezas previstas."
                if section.language == "es"
                else f"Little material today: {len(pieces)} of {n} planned pieces.")
    edition = SectionEdition(
        id=section.id, name=section.name, language=section.language, pieces=pieces,
        blocks=[b for r in results for b in r.blocks], recap=bool(recap),
        budget_words=words_budget, note=note,
    )
    return edition, spare, (target, hard, recap)


async def _top_up(ctx: Ctx, sections: list[Section], editions: list[SectionEdition],
                  spares: dict, plans: dict, total_budget: int) -> None:
    """Edition short by >10%: ask for one extra piece where the shortfall is largest."""
    if ctx.llm is None or not budget.needs_more(sum(e.words for e in editions), total_budget):
        return
    gaps = sorted(((e.budget_words - e.words, e) for e in editions if spares[e.id]),
                  key=lambda g: g[0], reverse=True)
    if not gaps:
        return
    edition = gaps[0][1]
    section = next(s for s in sections if s.id == edition.id)
    target, hard, recap = plans[edition.id]
    try:
        edition.pieces += await _write(ctx, section, spares[edition.id][:1], target, hard, recap,
                                       len(edition.pieces) + 10)
    except LLMError as exc:
        ctx.summary.llm_failures.append(f"{section.id} extra piece: {exc}")


async def run_build(opts: BuildOptions) -> Summary:
    cfg = load_sources()
    s = cfg.settings
    sections = [sec for sec in cfg.sections if not opts.sections or sec.id in opts.sections]
    if not sections:
        raise SystemExit(f"no section matches {opts.sections}; known: {[x.id for x in cfg.sections]}")
    day, now, since = _window(cfg, opts.day)
    minutes = opts.minutes or s.reading_time_minutes
    total = budget.total_budget(minutes, s.words_per_minute)
    # Shares come from all sections, so `--section f1` writes F1's usual share only.
    budgets = budget.section_budgets(total, {sec.id: sec.weight for sec in cfg.sections})
    total = sum(budgets[sec.id] for sec in sections)

    cache = Cache(CACHE_DIR / "cache.sqlite")
    llm = None if opts.no_llm else LLMClient(load_llm(), cache, force=opts.force, offline=opts.offline)
    summary = Summary(budget_words=total, llm=llm,
                      target_minutes=budget.reading_minutes(total, s.words_per_minute))
    async with make_client(s) as client:
        ctx = Ctx(cfg, opts, cache, None if opts.offline else client, llm, summary)
        fctx = FetchContext(since=since, now=now, settings=s)
        fetched = await asyncio.gather(*(_fetch_section(ctx, sec, fctx, day) for sec in sections))
        editions, spares, plans = [], {}, {}
        for sec, results in zip(sections, fetched, strict=True):
            _tally(summary, results)
            log.info("section %s: building", sec.id)
            ed, spare, plan = await build_section(ctx, sec, results, budgets[sec.id])
            editions.append(ed)
            spares[sec.id], plans[sec.id] = spare, plan

        kept = {id(p) for p in budget.trim_to_budget([p for e in editions for p in e.pieces], total)}
        for e in editions:
            e.pieces = [p for p in e.pieces if id(p) in kept]
        await _top_up(ctx, sections, editions, spares, plans, total)

    edition = Edition(date=day, language=cfg.sections[0].language,
                      words_per_minute=s.words_per_minute, target_minutes=minutes,
                      sections=_merge_previous(cfg, day, editions) if opts.sections else editions)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    summary.output = render_edition(edition, DIST_DIR)
    (summary.output / "edition.json").write_text(edition.model_dump_json(indent=1), "utf-8")
    summary.pieces = sum(len(e.pieces) for e in editions)
    summary.blocks = sum(len(e.blocks) for e in editions)
    summary.words = sum(e.words for e in editions)
    summary.minutes = budget.reading_minutes(summary.words, s.words_per_minute)
    return summary


def _merge_previous(cfg: SourcesConfig, day: date, fresh: list[SectionEdition]) -> list[SectionEdition]:
    """A --section rebuild replaces only its sections in the day's saved edition."""
    saved = DIST_DIR / day.isoformat() / "edition.json"
    old = {e.id: e for e in Edition.model_validate_json(saved.read_text()).sections} \
        if saved.exists() else {}
    new = {e.id: e for e in fresh}
    return [new.get(sec.id) or old[sec.id] for sec in cfg.sections if sec.id in new or sec.id in old]


def print_summary(summary: Summary, seconds: float) -> None:
    llm = summary.llm
    lines = [
        "",
        "=== David Times build summary ===",
        f"Sources OK: {summary.sources_ok}  failed: {len(summary.sources_failed)}  "
        f"skipped: {len(summary.sources_skipped)}",
        *(f"  FAILED  {x}" for x in summary.sources_failed),
        *(f"  skipped {x}" for x in summary.sources_skipped),
        f"Items fetched: {summary.items}  clusters: {summary.clusters}",
        f"Pieces written: {summary.pieces}  data blocks: {summary.blocks}",
        f"Words: {summary.words} / budget {summary.budget_words}  ->  about {summary.minutes} min "
        f"(target {summary.target_minutes} min, {summary.words / max(1, summary.budget_words):.0%})",
    ]
    if llm:
        st = llm.stats
        lines.append(f"LLM calls: {st.calls} {dict(st.by_provider)}  cache hits: {st.cache_hits}  "
                     f"tokens in/out (est.): {st.prompt_tokens}/{st.completion_tokens}")
    lines += [f"  LLM problem: {x}" for x in summary.llm_failures]
    lines += [f"Output: {summary.output}/index.html", f"Total time: {seconds:.1f}s"]
    print("\n".join(lines))


def build(opts: BuildOptions) -> int:
    started = time.monotonic()
    summary = asyncio.run(run_build(opts))
    print_summary(summary, time.monotonic() - started)
    if summary.pieces == 0 and summary.blocks == 0:
        return 1  # total failure: nothing to read
    return 0
