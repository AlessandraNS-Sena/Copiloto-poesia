"""Registra os pares A/B na planilha do experimento (data/experimento.xlsx).

Escreve apenas nas colunas de entrada da aba "Pins" e preserva as fórmulas.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
TRACKER = ROOT / "data" / "experimento.xlsx"

# Colunas da aba Pins (1 = A)
COL = {"par": 1, "versao": 2, "incluir": 3, "data": 4, "hora": 5, "poema": 6, "tema": 7,
       "titulo": 8, "descricao": 9, "palavras": 10, "pasta": 11, "link": 12}


def _next_pair_id(ws) -> str:
    nums = []
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, COL["par"]).value
        if isinstance(v, str) and v.upper().startswith("P") and v[1:].isdigit():
            if ws.cell(r, COL["incluir"]).value != "Não":  # ignora linhas de exemplo
                nums.append(int(v[1:]))
    return f"P{(max(nums) + 1) if nums else 1:02d}"


def _first_empty_row(ws) -> int:
    for r in range(2, ws.max_row + 2):
        if not ws.cell(r, COL["par"]).value and not ws.cell(r, COL["versao"]).value:
            return r
    return ws.max_row + 1


def next_pair_id(path: Path = TRACKER) -> str:
    try:
        return _next_pair_id(load_workbook(path, read_only=True)["Pins"])
    except Exception:
        return ""


def log_pair(poem_title: str, tema: str, pasta: str, when: dt.datetime,
             a: dict, b: dict, path: Path = TRACKER) -> str:
    """a/b: {"titulo", "descricao", "palavras", "link"}. Devolve o ID do par."""
    wb = load_workbook(path)
    ws = wb["Pins"]
    pair = _next_pair_id(ws)
    for version, data in (("A", a), ("B", b)):
        r = _first_empty_row(ws)
        values = {"par": pair, "versao": version, "incluir": "Sim", "data": when.date(),
                  "hora": when.time().replace(second=0, microsecond=0), "poema": poem_title,
                  "tema": tema, "titulo": data.get("titulo", ""), "descricao": data.get("descricao", ""),
                  "palavras": data.get("palavras", ""), "pasta": pasta, "link": data.get("link", "")}
        for k, v in values.items():
            ws.cell(r, COL[k]).value = v
    wb.save(path)
    return pair


def read_trends(path: Path = TRACKER) -> list[str]:
    """Termos marcados como 'Sim' na aba Pinterest Trends (ignora a linha de exemplo)."""
    try:
        wb = load_workbook(path, read_only=True)
        ws = wb["Pinterest Trends"]
    except Exception:
        return []
    terms = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        term, *_rest = row
        use = row[4] if len(row) > 4 else None
        notes = row[5] if len(row) > 5 else ""
        if term and use == "Sim" and "exemplo" not in str(notes or "").lower():
            terms.append(str(term))
    return terms
