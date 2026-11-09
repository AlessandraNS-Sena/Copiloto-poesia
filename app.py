"""Copiloto de distribuição de poesia — interface em Streamlit.

Rodar:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import io
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.analysis import baseline, insights_text, plot_figures
from src.copilot import Copilot, with_utm
from src.pin_image import THEMES, render_pin
from src.pinterest_parser import parse_export
from src.tracker import TRACKER, log_pair, next_pair_id, read_trends

load_dotenv()
ROOT = Path(__file__).parent
DEFAULT_CSV = ROOT / "data" / "raw" / "pinterest_analytics_2026-10-10_2026-11-09.csv"

st.set_page_config(page_title="Copiloto de Poesia", page_icon="✉️", layout="wide")


def pct(x, nd=1):
    return "—" if x is None else f"{x * 100:.{nd}f}%".replace(".", ",")


def num(x):
    return f"{int(x):,}".replace(",", ".")


@st.cache_data
def load_baseline(raw: bytes | None):
    path = DEFAULT_CSV
    if raw is not None:
        path = ROOT / "data" / "raw" / "_upload.csv"
        path.write_bytes(raw)
    exp = parse_export(path)
    b = baseline(exp)
    figs = plot_figures(exp, b, ROOT / "reports" / "figures")
    return exp, b, [str(f) for f in figs]


# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.header("Configuração")
    api_key = st.text_input("Chave da API (Anthropic)", value=os.getenv("ANTHROPIC_API_KEY", ""),
                            type="password", help="Sem chave, o app roda em modo demonstração.")
    substack = st.text_input("Link do post no Substack", placeholder="https://seunome.substack.com/p/...")
    pasta = st.text_input("Pasta do Pinterest", value="alvorecer")
    assinatura = st.text_input("Assinatura no pin", value=os.getenv("ASSINATURA", "@ale_nss"))
    tema_visual = st.selectbox("Visual do pin", list(THEMES), index=0)
    upload = st.file_uploader("Export mais recente do Pinterest (CSV)", type="csv")

exp, b, figs = load_baseline(upload.getvalue() if upload else None)
copilot = Copilot(api_key=api_key or None)

st.title("Copiloto de distribuição de poesia")
st.caption("Empacota cada poema para ser encontrado e salvo no Pinterest — sem nunca reescrevê-lo.")

aba_copiloto, aba_dados = st.tabs(["✍️ Copiloto", "📊 Linha de base"])

# ------------------------------------------------------------------ copiloto
with aba_copiloto:
    if copilot.demo:
        st.info("Modo demonstração: sem chave de API, as sugestões seguem regras fixas.")

    col_in, col_out = st.columns([1, 1], gap="large")
    with col_in:
        titulo_poema = st.text_input("Nome do poema (para a planilha)")
        tema = st.text_input("Tema", placeholder="saudade, amor, identidade…")
        poema = st.text_area("Poema", height=320, placeholder="Cole o poema aqui, com as quebras de verso.")
        trends = read_trends()
        if trends:
            st.caption("Palavras do Pinterest Trends usadas: " + ", ".join(trends))
        gerar = st.button("Gerar pacote", type="primary", disabled=not poema.strip())

    if gerar:
        with st.spinner("Empacotando…"):
            try:
                st.session_state.pkg = copilot.package(poema, tema=tema, insights=insights_text(b), trends=trends)
            except Exception as exc:
                st.error(f"Não consegui gerar: {exc}")

    pkg = st.session_state.get("pkg")
    with col_out:
        if not pkg:
            st.write("As sugestões aparecem aqui.")
        else:
            for alerta in pkg.alertas:
                st.warning(alerta)
            if pkg.avaliacao.get("nota"):
                st.metric("Aderência ao guia de voz", f"{pkg.avaliacao['nota']}/5")
                for p in pkg.avaliacao.get("problemas", []):
                    st.caption(f"• {p}")

            titulo = st.radio("Título do pin", pkg.titulos)
            trecho = st.radio("Trecho para a imagem", pkg.trechos, format_func=lambda t: t.replace("\n", " / "))
            descricao_b = st.text_area("Descrição (versão B · copiloto)", pkg.descricao, height=140)
            st.caption(f"{len(descricao_b)}/500 caracteres")
            palavras = st.text_input("Palavras-chave", ", ".join(pkg.palavras_chave))
            st.text_input("Subtítulo para o Substack", pkg.subtitulo_substack)
            if pkg.raciocinio:
                st.caption(f"Por que essas escolhas: {pkg.raciocinio}")

            img = render_pin(trecho, title=titulo, signature=assinatura, theme=tema_visual)
            st.image(img, width=320)
            buf = io.BytesIO(); img.save(buf, format="PNG")
            st.download_button("Baixar imagem do pin", buf.getvalue(), file_name="pin.png", mime="image/png")

            st.divider()
            st.subheader("Registrar o par A/B")
            descricao_a = st.text_area("Descrição simples (versão A · seu jeito atual)",
                                       placeholder="Ex.: poema novo no substack")
            c1, c2 = st.columns(2)
            dia = c1.date_input("Publicação", dt.date.today())
            hora = c2.time_input("Horário", dt.time(20, 0))
            par_id = next_pair_id()
            link_a = with_utm(substack, "A", par_id) if substack else ""
            link_b = with_utm(substack, "B", par_id) if substack else ""
            if substack:
                st.caption("Use estes links como destino de cada pin:")
                st.code(f"A: {link_a}\nB: {link_b}", language=None)
            else:
                st.warning("Sem link do Substack, o pin não gera tráfego (hoje: 0 cliques externos).")
            if st.button("Salvar na planilha do experimento", disabled=not descricao_a.strip()):
                try:
                    par = log_pair(titulo_poema or titulo, tema.strip().capitalize(), pasta,
                                   dt.datetime.combine(dia, hora),
                                   a={"titulo": titulo_poema or titulo, "descricao": descricao_a, "link": link_a},
                                   b={"titulo": titulo, "descricao": descricao_b, "palavras": palavras, "link": link_b})
                    st.success(f"Par {par} salvo em {TRACKER.name}. Publique os dois pins no mesmo horário.")
                except PermissionError:
                    st.error("A planilha está aberta em outro programa. Feche-a e tente de novo.")

# ------------------------------------------------------------------ dados
with aba_dados:
    ini, fim = b["periodo_com_dados"]
    st.subheader(f"Linha de base · {ini:%d/%m} a {fim:%d/%m/%Y}")
    st.caption(f"Conta convertida para comercial em 03/11; dados a partir de "
               f"{b['estimativa_a_partir_de']:%d/%m} são estimativas do Pinterest." if b["estimativa_a_partir_de"] else "")
    m = st.columns(5)
    m[0].metric("Impressões", num(b["impressoes_total_pastas"]))
    m[1].metric("Salvamentos", num(b["saves_total"]))
    m[2].metric("Cliques no pin", num(b["pin_clicks_total"]))
    m[3].metric("Cliques p/ Substack", num(b["outbound_clicks_total"]))
    m[4].metric("Pins com 80% do alcance", f"{b['pins_para_80pct']} de {b['n_pins']}")
    st.caption(f"Taxa de salvamento: {pct(b['taxa_salvamento'])} · clique no pin: {pct(b['taxa_clique_pin'])} · "
               f"engajamento: {pct(b['taxa_engajamento'])} · contagem de pins entre os {b['n_pins']} mais vistos.")
    for f in figs:
        st.image(f, width=760)
    tabela = b["por_pasta"][["board", "impressions", "saves", "pin_clicks", "outbound_clicks", "save_rate"]]
    st.dataframe(tabela.rename(columns={"board": "Pasta", "impressions": "Impressões", "saves": "Salvamentos",
                                        "pin_clicks": "Cliques no pin", "outbound_clicks": "Cliques externos",
                                        "save_rate": "Taxa de salvamento"}),
                 hide_index=True, column_config={"Taxa de salvamento": st.column_config.NumberColumn(format="percent")})
