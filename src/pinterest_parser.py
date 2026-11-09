"""Leitura do CSV "Analytics overview" exportado do Pinterest.

O arquivo exportado não é um CSV comum: ele tem várias seções empilhadas
(cabeçalho de filtros, série diária de impressões, Top Boards e Top Pins),
separadas por linhas em branco e com notas de rodapé. Este módulo separa as
seções e devolve cada uma como um DataFrame limpo.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ESTIMATE_RE = re.compile(r"Data starting from (\d{4}-\d{2}-\d{2}) is an estimate")


@dataclass
class PinterestExport:
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    filters: dict[str, str]
    daily: pd.DataFrame          # date, impressions, is_estimate
    boards: pd.DataFrame         # board, url, impressions, engagement, pin_clicks, outbound_clicks, saves
    pins: pd.DataFrame           # pin_id, url, content_type, source, canonical, impressions
    estimate_from: pd.Timestamp | None = None
    notes: list[str] = field(default_factory=list)


def _blocks(text: str) -> list[list[list[str]]]:
    """Quebra o arquivo em blocos separados por linhas vazias."""
    blocks, current = [], []
    for row in csv.reader(io.StringIO(text)):
        if not row or all(not c.strip() for c in row):
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(row)
    if current:
        blocks.append(current)
    return blocks


def _is_note(row: list[str]) -> bool:
    first = row[0].strip()
    return len(row) == 1 and (
        first.startswith("Data starting")
        or first.startswith("Top boards table")
        or first.startswith("Top pins table")
        or first == "Not enough data."
    )


def parse_export(path: str | Path) -> PinterestExport:
    text = Path(path).read_text(encoding="utf-8-sig")
    blocks = _blocks(text)
    notes: list[str] = []
    estimate_from = None

    # 1) Cabeçalho: título, período e filtros
    header = blocks[0]
    start, end = [s.strip() for s in header[1][0].split(" - ")]
    filters = {r[0]: (r[1] if len(r) > 1 else "") for r in header[2:]}

    daily = pd.DataFrame(columns=["date", "impressions"])
    boards = pd.DataFrame()
    pins = pd.DataFrame()

    for block in blocks[1:]:
        title = block[0]
        body = [r for r in block[1:] if not _is_note(r)]
        for r in block:
            if _is_note(r):
                notes.append(r[0])
                m = ESTIMATE_RE.search(r[0])
                if m:
                    estimate_from = pd.Timestamp(m.group(1))

        if title[:2] == ["Date", "Impressions"]:
            daily = pd.DataFrame(body, columns=["date", "impressions"])
            daily["date"] = pd.to_datetime(daily["date"])
            daily["impressions"] = pd.to_numeric(daily["impressions"], errors="coerce")

        elif title[0].startswith("Top Boards"):
            cols = ["url", "impressions", "engagement", "pin_clicks", "outbound_clicks", "saves"]
            rows = [r for r in body[1:] if len(r) == len(cols)]
            boards = pd.DataFrame(rows, columns=cols)
            for c in cols[1:]:
                boards[c] = pd.to_numeric(boards[c], errors="coerce").fillna(0).astype(int)
            boards.insert(0, "board", boards["url"].str.rstrip("/").str.split("/").str[-1])

        elif title[0].startswith("Top Pins"):
            cols = ["url", "content_type", "source", "canonical", "impressions"]
            rows = [r for r in body[1:] if len(r) == len(cols)]
            pins = pd.DataFrame(rows, columns=cols)
            pins["impressions"] = pd.to_numeric(pins["impressions"], errors="coerce").fillna(0).astype(int)
            pins.insert(0, "pin_id", pins["url"].str.rstrip("/").str.split("/").str[-1])

    if estimate_from is not None and not daily.empty:
        daily["is_estimate"] = daily["date"] >= estimate_from
    elif not daily.empty:
        daily["is_estimate"] = False

    return PinterestExport(
        period_start=pd.Timestamp(start),
        period_end=pd.Timestamp(end),
        filters=filters,
        daily=daily,
        boards=boards,
        pins=pins,
        estimate_from=estimate_from,
        notes=notes,
    )
