"""Métricas de linha de base a partir do export do Pinterest."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .pinterest_parser import PinterestExport

VINHO = "#7A2E3B"
CINZA = "#B9A9AC"


def _rate(num: float, den: float) -> float | None:
    return None if not den else num / den


def baseline(exp: PinterestExport) -> dict:
    daily = exp.daily.dropna(subset=["impressions"])
    boards = exp.boards
    pins = exp.pins.sort_values("impressions", ascending=False)

    tot_impr = int(boards["impressions"].sum()) if not boards.empty else 0
    tot = {c: int(boards[c].sum()) for c in ["engagement", "pin_clicks", "outbound_clicks", "saves"]}

    by_board = boards.copy()
    by_board["share_impressions"] = by_board["impressions"] / tot_impr if tot_impr else 0
    by_board["save_rate"] = by_board.apply(lambda r: _rate(r.saves, r.impressions), axis=1)
    by_board["engagement_rate"] = by_board.apply(lambda r: _rate(r.engagement, r.impressions), axis=1)
    by_board["click_rate"] = by_board.apply(lambda r: _rate(r.pin_clicks, r.impressions), axis=1)

    pins_impr = int(pins["impressions"].sum())
    top5 = int(pins.head(5)["impressions"].sum())
    top10 = int(pins.head(10)["impressions"].sum())
    # Quantos pins concentram 80% das impressões
    cum = pins["impressions"].cumsum() / pins_impr if pins_impr else pd.Series(dtype=float)
    n80 = int((cum < 0.8).sum() + 1) if pins_impr else 0

    first_day = daily.iloc[0] if not daily.empty else None
    last_day = daily.iloc[-1] if not daily.empty else None

    return {
        "periodo_com_dados": (daily["date"].min(), daily["date"].max()),
        "dias_com_dados": int(len(daily)),
        "impressoes_total_diario": int(daily["impressions"].sum()),
        "impressoes_total_pastas": tot_impr,
        "impressoes_media_dia": float(daily["impressions"].mean()) if not daily.empty else 0,
        "primeiro_dia": first_day,
        "ultimo_dia": last_day,
        "queda_primeiro_ultimo": _rate(last_day.impressions - first_day.impressions, first_day.impressions)
        if first_day is not None else None,
        "estimativa_a_partir_de": exp.estimate_from,
        **{f"{k}_total": v for k, v in tot.items()},
        "taxa_salvamento": _rate(tot["saves"], tot_impr),
        "taxa_engajamento": _rate(tot["engagement"], tot_impr),
        "taxa_clique_pin": _rate(tot["pin_clicks"], tot_impr),
        "taxa_clique_externo": _rate(tot["outbound_clicks"], tot_impr),
        "n_pins": int(len(pins)),
        "share_top5": _rate(top5, pins_impr),
        "share_top10": _rate(top10, pins_impr),
        "pins_para_80pct": n80,
        "por_pasta": by_board,
        "pins_ordenados": pins.reset_index(drop=True),
    }


def _pct(x: float | None, nd: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{nd}f}%".replace(".", ",")


def insights_text(b: dict) -> str:
    """Resumo dos achados em texto, usado como contexto pelo copiloto."""
    pasta = b["por_pasta"].sort_values("impressions", ascending=False).iloc[0]
    linhas = [
        f"- A pasta \"{pasta.board}\" concentra {_pct(pasta.share_impressions, 0)} das impressões; "
        f"taxa de salvamento {_pct(b['taxa_salvamento'])}, clique no pin {_pct(b['taxa_clique_pin'])}.",
        f"- Entre os {b['n_pins']} pins mais vistos, {b['pins_para_80pct']} fazem 80% das impressões: "
        "o título e o trecho de cada pin pesam muito.",
    ]
    if b["outbound_clicks_total"] == 0:
        linhas.append("- 0 cliques externos: os pins ainda não levam ao Substack. "
                      "Toda descrição precisa de um convite claro para ler o poema completo.")
    return "\n".join(linhas)


def plot_figures(exp: PinterestExport, b: dict, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    paths = []

    # 1. Impressões por dia
    d = exp.daily.dropna(subset=["impressions"])
    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=150)
    colors = [CINZA if e else VINHO for e in d["is_estimate"]]
    ax.bar(d["date"].dt.strftime("%d/%m"), d["impressions"], color=colors)
    for x, y in zip(d["date"].dt.strftime("%d/%m"), d["impressions"]):
        ax.text(x, y, f"{int(y):,}".replace(",", "."), ha="center", va="bottom", fontsize=8)
    ax.set_title("Impressões por dia desde a conversão da conta", loc="left", fontsize=11)
    ax.set_ylabel("Impressões")
    if d["is_estimate"].any():
        ax.text(0.99, 0.95, "cinza = estimativa do Pinterest", transform=ax.transAxes,
                ha="right", va="top", fontsize=8, color="#666")
    fig.tight_layout()
    p = out / "01_impressoes_por_dia.png"; fig.savefig(p); plt.close(fig); paths.append(p)

    # 2. Concentração: curva acumulada de impressões por pin
    pins = b["pins_ordenados"]
    cum = pins["impressions"].cumsum() / pins["impressions"].sum() * 100
    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=150)
    ax.plot(range(1, len(cum) + 1), cum, color=VINHO, lw=2)
    ax.axhline(80, color=CINZA, ls="--", lw=1)
    ax.axvline(b["pins_para_80pct"], color=CINZA, ls="--", lw=1)
    ax.text(b["pins_para_80pct"] + 0.8, 40, f"{b['pins_para_80pct']} dos {len(pins)} pins mais vistos\n= 80% das impressões",
            fontsize=9, color="#333")
    ax.set_xlabel("Pins, do mais visto ao menos visto")
    ax.set_ylabel("% acumulado das impressões")
    ax.set_ylim(0, 102)
    ax.set_title("Poucos pins concentram o alcance", loc="left", fontsize=11)
    fig.tight_layout()
    p = out / "02_concentracao_pins.png"; fig.savefig(p); plt.close(fig); paths.append(p)

    # 3. Funil da pasta principal
    top = b["por_pasta"].sort_values("impressions", ascending=False).iloc[0]
    etapas = ["Impressões", "Engajamentos", "Cliques no pin", "Salvamentos", "Cliques p/ Substack"]
    vals = [top.impressions, top.engagement, top.pin_clicks, top.saves, top.outbound_clicks]
    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=150)
    ax.barh(etapas[::-1], vals[::-1], color=[VINHO if v else CINZA for v in vals[::-1]])
    ax.set_xscale("symlog", linthresh=10)
    for i, v in enumerate(vals[::-1]):
        pct = "" if v == top.impressions else f"  ({v / top.impressions:.2%})".replace(".", ",")
        ax.text(max(v, 1) * 1.1, i, f"{int(v):,}".replace(",", ".") + pct, va="center", fontsize=9)
    ax.set_xlim(0, top.impressions * 6)
    ax.set_xticks([])
    ax.set_title(f"Funil da pasta \"{top.board}\": o caminho até o Substack para no zero",
                 loc="left", fontsize=11)
    fig.tight_layout()
    p = out / "03_funil_pasta_principal.png"; fig.savefig(p); plt.close(fig); paths.append(p)
    return paths
