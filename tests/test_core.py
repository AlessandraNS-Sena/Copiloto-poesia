import shutil
from pathlib import Path

from openpyxl import load_workbook

from src.analysis import baseline
from src.copilot import Copilot, is_verbatim, with_utm, Package
from src.pin_image import render_pin
from src.pinterest_parser import parse_export
from src import tracker

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "raw" / "pinterest_analytics_2026-10-10_2026-11-09.csv"

POEMA = """deixei a janela aberta
pra você saber o caminho
mesmo que a casa
já não tenha o seu nome
a chaleira ainda canta
às sete da manhã"""


def test_parser_reconcilia_totais():
    e = parse_export(CSV)
    assert len(e.daily.dropna()) == 6
    assert e.daily["impressions"].sum() == 20300
    assert e.boards["impressions"].sum() == 20292  # diferença de 8 = arredondamento do Pinterest
    assert len(e.pins) == 50
    assert str(e.estimate_from.date()) == "2026-11-08"


def test_baseline():
    b = baseline(parse_export(CSV))
    assert b["saves_total"] == 264 and b["outbound_clicks_total"] == 0
    assert round(b["taxa_salvamento"], 4) == 0.0130
    assert b["pins_para_80pct"] == 14


def test_trecho_literal():
    assert is_verbatim("deixei a janela aberta\npra você saber o caminho", POEMA)
    assert is_verbatim("DEIXEI a janela   aberta", POEMA)
    assert not is_verbatim("deixei a porta aberta", POEMA)


def test_guardrail_descarta_trecho_inventado():
    c = Copilot(api_key=None)
    pkg = Package(titulos=["x"], descricao="d" * 600, palavras_chave=[],
                  trechos=["um verso que não existe", "a chaleira ainda canta"], subtitulo_substack="")
    c._guardrails(pkg, POEMA)
    assert pkg.trechos == ["a chaleira ainda canta"]
    assert len(pkg.descricao) <= 500
    assert len(pkg.alertas) == 2


def test_modo_demo_gera_pacote_valido():
    pkg = Copilot(api_key=None).package(POEMA, tema="saudade")
    assert pkg.modo == "demo"
    assert all(is_verbatim(t, POEMA) for t in pkg.trechos)


def test_utm():
    url = with_utm("https://exemplo.substack.com/p/poema", "B", "P03")
    assert "utm_source=pinterest" in url and "utm_content=p03-b" in url


def test_imagem_do_pin():
    img = render_pin("deixei a janela aberta\npra você saber o caminho", title="janela")
    assert img.size == (1000, 1500)


def test_registro_preserva_formulas(tmp_path, monkeypatch):
    dst = tmp_path / "exp.xlsx"
    shutil.copy(ROOT / "data" / "experimento.xlsx", dst)
    import datetime as dt
    par = tracker.log_pair("janela", "Saudade", "alvorecer", dt.datetime(2026, 11, 10, 20, 0),
                           a={"titulo": "janela", "descricao": "poema novo"},
                           b={"titulo": "poema de saudade", "descricao": "..."}, path=dst)
    assert par == "P01"
    ws = load_workbook(dst)["Pins"]
    assert ws["A4"].value == "P01" and ws["B4"].value == "A" and ws["B5"].value == "B"
    assert str(ws["Q4"].value).startswith("=")


def test_fluxo_com_modelo_simulado():
    """Simula a resposta do modelo para testar o caminho com API sem gastar créditos."""
    import json
    from types import SimpleNamespace

    resposta = {
        "titulos": ["poema de saudade para quem foi embora", "o caminho de volta", "janela aberta"],
        "descricao": "Um poema curto sobre saudade e casa. O poema inteiro está no Substack.",
        "palavras_chave": ["poemas de saudade", "poesia brasileira"],
        "trechos": ["a chaleira ainda canta\nàs sete da manhã", "um verso inventado pelo modelo"],
        "subtitulo_substack": "sobre deixar a janela aberta",
        "raciocinio": "Usei 'poemas de saudade' porque é um termo buscado.",
    }
    revisao = {"nota": 4, "problemas": [], "veredito": "aprovar"}
    respostas = iter([resposta, revisao])

    def create(**kwargs):
        texto = "Aqui está:\n" + json.dumps(next(respostas), ensure_ascii=False)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)])

    c = Copilot(api_key=None)
    c._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    pkg = c.package(POEMA, tema="saudade")
    assert pkg.modo == "llm"
    assert pkg.trechos == ["a chaleira ainda canta\nàs sete da manhã"]
    assert pkg.avaliacao["nota"] == 4
    assert any("descartado" in a for a in pkg.alertas)
