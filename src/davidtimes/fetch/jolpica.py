"""Jolpica-F1 (Ergast successor): last race, standings, next race. Numbers only."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from davidtimes.config import Section, Source
from davidtimes.fetch import FetchContext
from davidtimes.models import Block, FetchResult

API = "https://api.jolpi.ca/ergast/f1/current"


async def _get(client: httpx.AsyncClient, path: str) -> dict:
    resp = await client.get(f"{API}/{path}")
    resp.raise_for_status()
    return resp.json()["MRData"]


def _race_time(race: dict) -> datetime:
    time = race.get("time", "12:00:00Z").replace("Z", "+00:00")
    return datetime.fromisoformat(f"{race['date']}T{time}").astimezone(UTC)


def results_block(race: dict, top: int = 10) -> Block:
    rows = [
        [
            r["position"],
            f"{r['Driver']['givenName'][0]}. {r['Driver']['familyName']}",
            r["Constructor"]["name"],
            r["points"],
        ]
        for r in race["Results"][:top]
    ]
    return Block(
        title=f"{race['raceName']} — resultado",
        columns=["Pos", "Piloto", "Equipo", "Pts"],
        rows=rows,
        note=f"Ronda {race['round']}, {race['date']}",
    )


def driver_block(standings: dict, top: int = 10) -> Block:
    rows = [
        [s["position"] if "position" in s else s.get("positionText", "-"),
         f"{s['Driver']['givenName'][0]}. {s['Driver']['familyName']}",
         s["points"]]
        for s in standings["DriverStandings"][:top]
    ]
    return Block(title="Campeonato de pilotos", columns=["Pos", "Piloto", "Pts"], rows=rows)


def constructor_block(standings: dict) -> Block:
    rows = [
        [s.get("position", s.get("positionText", "-")), s["Constructor"]["name"], s["points"]]
        for s in standings["ConstructorStandings"]
    ]
    return Block(title="Campeonato de constructores", columns=["Pos", "Equipo", "Pts"], rows=rows)


def next_block(race: dict) -> Block:
    when = _race_time(race)
    return Block(
        title="Próxima carrera",
        columns=["Carrera", "Circuito", "Fecha (UTC)"],
        rows=[[race["raceName"], race["Circuit"]["circuitName"], when.strftime("%Y-%m-%d %H:%M")]],
    )


async def fetch(
    client: httpx.AsyncClient, source: Source, section: Section, ctx: FetchContext
) -> FetchResult:
    last = (await _get(client, "last/results.json"))["RaceTable"]["Races"]
    drivers = (await _get(client, "driverStandings.json"))["StandingsTable"]["StandingsLists"]
    teams = (await _get(client, "constructorStandings.json"))["StandingsTable"]["StandingsLists"]
    upcoming = (await _get(client, "next.json"))["RaceTable"]["Races"]

    blocks, event = [], False
    if last:
        blocks.append(results_block(last[0]))
        event = _race_time(last[0]) >= ctx.since
    if drivers:
        blocks.append(driver_block(drivers[0]))
    if teams:
        blocks.append(constructor_block(teams[0]))
    if upcoming:
        blocks.append(next_block(upcoming[0]))
    return FetchResult(source=source.name, blocks=blocks, event_in_window=event)
