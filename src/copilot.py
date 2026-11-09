"""Copiloto de distribuição: empacota um poema para o Pinterest e o Substack.

Regra central do produto: o agente NUNCA reescreve o poema. Ele só sugere
título, descrição, palavras-chave e escolhe trechos, que precisam ser cópias
literais de versos do poema. Essa regra é verificada por código (não só pelo
prompt), e uma segunda chamada ao modelo avalia a aderência ao guia de voz.

Sem ANTHROPIC_API_KEY, roda em "modo demonstração", com regras simples, para
que a interface funcione mesmo sem chave.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

ROOT = Path(__file__).resolve().parents[1]
VOICE_GUIDE = ROOT / "prompts" / "guia_de_voz.md"

# Limites do Pinterest para pins
MAX_TITLE = 100
MAX_DESCRIPTION = 500

DEFAULT_MODEL = os.getenv("COPILOTO_MODEL", "claude-sonnet-5-5")


# ----------------------------------------------------------------- utilidades
def _norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def is_verbatim(excerpt: str, poem: str) -> bool:
    """O trecho precisa existir literalmente no poema (ignorando espaços e caixa)."""
    return bool(excerpt.strip()) and _norm(excerpt) in _norm(poem)


def with_utm(url: str, version: str, pair_id: str = "", campaign: str = "copiloto-poesia") -> str:
    """Acrescenta parâmetros UTM ao link do Substack para identificar a origem do tráfego."""
    if not url:
        return ""
    parts = urlparse(url if "://" in url else "https://" + url)
    query = dict(parse_qsl(parts.query))
    query.update({
        "utm_source": "pinterest",
        "utm_medium": "social",
        "utm_campaign": campaign,
        "utm_content": f"{pair_id}-{version}".strip("-").lower(),
    })
    return urlunparse(parts._replace(query=urlencode(query)))


def load_voice_guide() -> str:
    return VOICE_GUIDE.read_text(encoding="utf-8") if VOICE_GUIDE.exists() else ""


# ----------------------------------------------------------------- resultado
@dataclass
class Package:
    titulos: list[str]
    descricao: str
    palavras_chave: list[str]
    trechos: list[str]
    subtitulo_substack: str
    raciocinio: str = ""
    avaliacao: dict = field(default_factory=dict)
    alertas: list[str] = field(default_factory=list)
    modo: str = "llm"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ----------------------------------------------------------------- prompts
SYSTEM = """Você é o copiloto de distribuição de uma poeta brasileira que publica no Pinterest e no Substack.
Seu trabalho é EMPACOTAR o poema para ser encontrado e salvo, nunca reescrevê-lo.

Regras inegociáveis:
1. Não altere, resuma nem "melhore" o poema. Os trechos devem ser cópias LITERAIS de versos consecutivos.
2. Respeite o guia de voz da autora acima de qualquer boa prática genérica de marketing.
3. O Pinterest funciona como buscador: use na descrição, de forma natural, termos que as pessoas pesquisam
   (ex.: "poemas de saudade", "frases de amor", "poesia brasileira"), sem empilhar hashtags.
4. Título com no máximo {max_title} caracteres; descrição com no máximo {max_desc} caracteres.
5. A descrição termina com um convite para ler o poema completo no Substack, no tom da autora.
6. Trechos para a imagem do pin: de 1 a 4 versos, que façam sentido sozinhos e caibam numa imagem vertical.

Responda APENAS com um objeto JSON válido, sem texto antes ou depois, neste formato:
{{
  "titulos": ["...", "...", "..."],
  "descricao": "...",
  "palavras_chave": ["...", "..."],
  "trechos": ["...", "..."],
  "subtitulo_substack": "...",
  "raciocinio": "1 a 3 frases explicando as escolhas, citando os dados quando usar"
}}"""

USER = """# Guia de voz da autora
{voice}

# O que os dados já mostram
{insights}

# Palavras-chave em alta (Pinterest Trends, anotadas pela autora)
{trends}

# Tema informado pela autora
{tema}

# Poema
<poema>
{poema}
</poema>"""

REVIEW_SYSTEM = """Você revisa o trabalho de um copiloto de marketing para uma poeta.
Compare o pacote com o guia de voz e responda APENAS com JSON:
{"nota": 1-5, "problemas": ["..."], "veredito": "aprovar" | "revisar"}
Nota 5 = soa exatamente como a autora; 1 = soa genérico ou contradiz o guia."""


DEFAULT_INSIGHTS = (
    "- Pasta principal concentra 98% das impressões; taxa de salvamento de 1,3% e de clique no pin de 4,1%.\n"
    "- 0 cliques externos: os pins ainda não levam ao Substack. Toda descrição precisa de um convite claro.\n"
    "- Entre os 50 pins mais vistos, 14 fazem 80% das impressões: vale caprichar no trecho e no título de cada pin."
)


# ----------------------------------------------------------------- agente
class Copilot:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self._client = None
        if self.api_key:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)

    @property
    def demo(self) -> bool:
        return self._client is None

    # --- chamada ao modelo
    def _ask(self, system: str, user: str, max_tokens: int = 1200) -> dict:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError(f"O modelo não devolveu JSON: {text[:200]}")
        return json.loads(match.group(0))

    # --- fluxo principal
    def package(self, poem: str, tema: str = "", insights: str = DEFAULT_INSIGHTS,
                trends: list[str] | None = None, review: bool = True) -> Package:
        poem = poem.strip()
        if not poem:
            raise ValueError("Cole um poema primeiro.")
        if self.demo:
            pkg = self._demo_package(poem, tema, trends or [])
        else:
            data = self._ask(
                SYSTEM.format(max_title=MAX_TITLE, max_desc=MAX_DESCRIPTION),
                USER.format(voice=load_voice_guide() or "(guia não preenchido)",
                            insights=insights or "(sem dados ainda)",
                            trends=", ".join(trends) if trends else "(nenhuma anotada)",
                            tema=tema or "(não informado)", poema=poem),
            )
            pkg = Package(
                titulos=[t.strip() for t in data.get("titulos", [])][:3],
                descricao=data.get("descricao", "").strip(),
                palavras_chave=[k.strip() for k in data.get("palavras_chave", [])],
                trechos=[t.strip() for t in data.get("trechos", [])],
                subtitulo_substack=data.get("subtitulo_substack", "").strip(),
                raciocinio=data.get("raciocinio", "").strip(),
            )
        self._guardrails(pkg, poem)
        if review and not self.demo:
            pkg.avaliacao = self._review(pkg)
        return pkg

    # --- verificações feitas por código, não pelo modelo
    def _guardrails(self, pkg: Package, poem: str) -> None:
        ok = [t for t in pkg.trechos if is_verbatim(t, poem)]
        removed = len(pkg.trechos) - len(ok)
        if removed:
            pkg.alertas.append(f"{removed} trecho(s) descartado(s) por não ser(em) cópia literal do poema.")
        if not ok:
            ok = [_first_lines(poem)]
            pkg.alertas.append("Nenhum trecho válido; usei os primeiros versos do poema.")
        pkg.trechos = ok
        if len(pkg.descricao) > MAX_DESCRIPTION:
            pkg.descricao = pkg.descricao[: MAX_DESCRIPTION - 1].rsplit(" ", 1)[0] + "…"
            pkg.alertas.append(f"Descrição cortada para {MAX_DESCRIPTION} caracteres (limite do Pinterest).")
        pkg.titulos = [t[:MAX_TITLE] for t in pkg.titulos if t] or [_first_lines(poem, 1)[:MAX_TITLE]]

    def _review(self, pkg: Package) -> dict:
        try:
            return self._ask(
                REVIEW_SYSTEM,
                f"# Guia de voz\n{load_voice_guide()}\n\n# Pacote\n"
                + json.dumps(pkg.to_dict(), ensure_ascii=False, indent=2),
                max_tokens=400,
            )
        except Exception as exc:  # a revisão é um extra; não derruba o fluxo
            return {"nota": None, "problemas": [f"revisão indisponível: {exc}"], "veredito": "revisar"}

    # --- modo demonstração (sem chave de API)
    def _demo_package(self, poem: str, tema: str, trends: list[str]) -> Package:
        lines = [l.strip() for l in poem.splitlines() if l.strip()]
        tema_l = (tema or "poesia").lower()
        kws = list(dict.fromkeys([f"poemas de {tema_l}" if tema else "poemas curtos",
                                  "poesia brasileira", "frases para refletir", *trends]))[:6]
        trechos = []
        if lines:
            trechos.append("\n".join(lines[:2]))
            if len(lines) > 3:
                trechos.append("\n".join(lines[-2:]))
        desc = (f"Um poema curto sobre {tema_l}, para salvar e reler. "
                f"{lines[0] if lines else ''} … O poema inteiro está no Substack.")
        return Package(
            titulos=[lines[0][:MAX_TITLE] if lines else "poema", f"poema sobre {tema_l}",
                     f"{tema_l}: um poema curto"],
            descricao=desc,
            palavras_chave=kws,
            trechos=trechos,
            subtitulo_substack=f"um poema sobre {tema_l}",
            raciocinio="Modo demonstração: regras fixas, sem modelo de linguagem. "
                       "Configure ANTHROPIC_API_KEY para gerar sugestões de verdade.",
            modo="demo",
        )


def _first_lines(poem: str, n: int = 2) -> str:
    lines = [l.strip() for l in poem.splitlines() if l.strip()]
    return "\n".join(lines[:n])
