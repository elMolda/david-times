"""football-data.org v4 (free tier, needs FOOTBALL_DATA_API_KEY)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import httpx

from davidtimes.config import Section, Source
from davidtimes.fetch import FetchContext, SkipSource
from davidtimes.models import Block, FetchResult

API = "https://api.football-data.org/v4"


def _team(t: dict) -> str:
    return t.get("shortName") or t.get("name") or "?"


def standings_block(data: dict) -> Block:
    table = next(s for s in data["standings"] if s["type"] == "TOTAL")["table"]
    rows = [
        [str(r["position"]), _team(r["team"]), str(r["playedGames"]),
         str(r["goalDifference"]), str(r["points"])]
        for r in table
    ]
    return Block(title="Tabla", columns=["#", "Equipo", "PJ", "DG", "Pts"], rows=rows)


def results_block(matches: list[dict]) -> Block:
    rows = [
        [_team(m["homeTeam"]),
         f"{m['score']['fullTime']['home']}–{m['score']['fullTime']['away']}",
         _team(m["awayTeam"])]
        for m in matches
    ]
    return Block(title="Últimos resultados", columns=["Local", "", "Visitante"], rows=rows)


def fixtures_block(matches: list[dict]) -> Block:
    rows = [
        [m["utcDate"][:16].replace("T", " "), _team(m["homeTeam"]), _team(m["awayTeam"])]
        for m in matches
    ]
    return Block(title="Próximos partidos (UTC)", columns=["Fecha", "Local", "Visitante"], rows=rows)


async def fetch(
    client: httpx.AsyncClient, source: Source, section: Section, ctx: FetchContext
) -> FetchResult:
    key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not key:
        raise SkipSource("FOOTBALL_DATA_API_KEY not set")
    comp = source.param("competition", "PL")
    headers = {"X-Auth-Token": key}

    async def get(path: str, **params: str) -> dict:
        resp = await client.get(f"{API}/competitions/{comp}/{path}", headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    today = ctx.now.date()
    standings = await get("standings")
    finished = (await get("matches", status="FINISHED",
                          dateFrom=(today - timedelta(days=7)).isoformat(),
                          dateTo=today.isoformat()))["matches"]
    upcoming = (await get("matches", status="SCHEDULED,TIMED",
                          dateFrom=today.isoformat(),
                          dateTo=(today + timedelta(days=10)).isoformat()))["matches"]

    last_md = max((m["matchday"] for m in finished), default=None)
    last_round = [m for m in finished if m["matchday"] == last_md]
    event = any(
        datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")) >= ctx.since
        for m in finished
    )
    blocks = [standings_block(standings)]
    if last_round:
        blocks.append(results_block(last_round))
    if upcoming:
        blocks.append(fixtures_block(upcoming[:10]))
    return FetchResult(source=source.name, blocks=blocks, event_in_window=event)
