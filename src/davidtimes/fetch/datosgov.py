"""TRM (COP/USD official rate) from datos.gov.co (open, no key)."""

from __future__ import annotations

import httpx

from davidtimes.config import Section, Source
from davidtimes.fetch import FetchContext
from davidtimes.models import Block, FetchResult

API = "https://www.datos.gov.co/resource/32sa-8pi3.json"


def trm_block(rows: list[dict]) -> Block:
    table = []
    for i, r in enumerate(rows[:5]):
        value = float(r["valor"])
        change = ""
        if i + 1 < len(rows):
            change = f"{value - float(rows[i + 1]['valor']):+,.2f}"
        table.append([r["vigenciadesde"][:10], f"{value:,.2f}", change])
    return Block(title="TRM (COP por USD)", columns=["Vigente desde", "Valor", "Cambio"], rows=table,
                 note="Fuente: Superintendencia Financiera vía datos.gov.co")


async def fetch(
    client: httpx.AsyncClient, source: Source, section: Section, ctx: FetchContext
) -> FetchResult:
    resp = await client.get(API, params={"$order": "vigenciadesde DESC", "$limit": "6"})
    resp.raise_for_status()
    return FetchResult(source=source.name, blocks=[trm_block(resp.json())])
