"""Gera a imagem vertical do pin (1000 x 1500, proporção 2:3 recomendada pelo Pinterest).

Template fixo e tipográfico, sem geração de imagem por IA: o visual fica
consistente entre os pins e a identidade é da autora.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "assets" / "fonts"

W, H = 1000, 1500
MARGIN = 110

THEMES = {
    "papel": {"bg": "#F4ECE1", "text": "#2B2124", "accent": "#7A2E3B", "muted": "#8C7B76"},
    "vinho": {"bg": "#4A1C26", "text": "#F6EDE3", "accent": "#E7C9A9", "muted": "#C9A9A6"},
    "alvorecer": {"bg": "#F7E3D7", "text": "#3A2328", "accent": "#C0646B", "muted": "#9A7B76"},
}


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONTS / name
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    """Quebra por largura em pixels, preservando as quebras de verso da autora."""
    out = []
    for verse in text.splitlines():
        words, line = verse.split(), ""
        if not words:
            out.append("")
            continue
        for w in words:
            test = f"{line} {w}".strip()
            if draw.textlength(test, font=font) <= max_w:
                line = test
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def _fit(draw, text: str, font_name: str, max_w: int, max_h: int, start: int = 76, minimum: int = 34):
    """Escolhe o maior tamanho de fonte em que o trecho cabe na caixa.

    Primeiro tenta um tamanho em que nenhum verso precise ser quebrado
    (respeita o ritmo do poema); se só der com letra muito pequena,
    aceita quebrar versos longos.
    """
    n_verses = len(text.splitlines()) or 1
    for size in range(start, 46 - 1, -2):
        font = _font(font_name, size)
        lines = _wrap(draw, text, font, max_w)
        line_h = int(size * 1.45)
        if len(lines) == n_verses and line_h * len(lines) <= max_h:
            return font, lines, line_h
    for size in range(start, minimum - 1, -2):
        font = _font(font_name, size)
        lines = _wrap(draw, text, font, max_w)
        line_h = int(size * 1.45)
        if line_h * len(lines) <= max_h:
            return font, lines, line_h
    font = _font(font_name, minimum)
    return font, _wrap(draw, text, font, max_w), int(minimum * 1.45)


def render_pin(excerpt: str, title: str = "", signature: str = "@ale_nss",
               theme: str = "papel", cta: str = "poema completo no substack") -> Image.Image:
    c = THEMES.get(theme, THEMES["papel"])
    img = Image.new("RGB", (W, H), c["bg"])
    d = ImageDraw.Draw(img)

    # moldura fina
    d.rectangle([40, 40, W - 40, H - 40], outline=c["muted"], width=2)

    # título no topo
    y = 150
    if title:
        tf = _font("PlayfairDisplay.ttf", 44)
        for line in _wrap(d, title, tf, W - 2 * MARGIN)[:2]:
            d.text((W / 2, y), line, font=tf, fill=c["accent"], anchor="ma")
            y += 58
    d.line([(W / 2 - 40, y + 20), (W / 2 + 40, y + 20)], fill=c["accent"], width=3)

    # trecho centralizado na área útil
    top, bottom = y + 80, H - 300
    font, lines, lh = _fit(d, excerpt, "Lora-Italic.ttf", W - 2 * MARGIN, bottom - top)
    block_h = lh * len(lines)
    ty = top + (bottom - top - block_h) / 2
    for line in lines:
        d.text((W / 2, ty), line, font=font, fill=c["text"], anchor="ma")
        ty += lh

    # rodapé: assinatura e convite
    d.text((W / 2, H - 230), signature, font=_font("PlayfairDisplay.ttf", 38), fill=c["text"], anchor="ma")
    d.text((W / 2, H - 165), cta, font=_font("Lora.ttf", 28), fill=c["muted"], anchor="ma")
    return img
