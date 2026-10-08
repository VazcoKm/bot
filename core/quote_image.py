"""Imagen de cita (el comando `quote`): avatar en escala de grises a la izquierda que se
desvanece, comilla, texto grande y firma. Todo con Pillow, sin servicios externos.

Para añadir una fuente: copia el .ttf a assets/fonts/ y regístrala en FONTS.
Para añadir un tema o layout: agrégalo a THEMES / LAYOUTS (el comando los muestra solo).
"""
from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# clave: (nombre visible, archivo normal, archivo negrita o None si es una fuente variable, ejes variables)
FONTS = {
    "poppins": ("Poppins", "Poppins-Medium.ttf", "Poppins-SemiBold.ttf", None),
    "playfair": ("Playfair Display", "PlayfairDisplay-Variable.ttf", "PlayfairDisplay-Variable.ttf", (500, 800)),
    "mono": ("Space Mono", "SpaceMono-Regular.ttf", "SpaceMono-Bold.ttf", None),
}

THEMES = {
    "white": {"label": "White", "bg": (8, 8, 10), "text": (246, 246, 246), "muted": (128, 128, 134), "quote": (74, 74, 80)},
    "black": {"label": "Black", "bg": (244, 244, 245), "text": (14, 14, 16), "muted": (110, 110, 116), "quote": (190, 190, 196)},
    "blue": {"label": "Blue", "bg": (8, 13, 30), "text": (232, 239, 255), "muted": (120, 142, 196), "quote": (58, 82, 148)},
}

LAYOUTS = {
    "wide": {"label": "Classic (wide)", "size": (1200, 630)},
    "square": {"label": "Square", "size": (1000, 1000)},
    "minimal": {"label": "Minimal (sin avatar)", "size": (1200, 500)},
}


def _font(key: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    _, regular, strong, axes = FONTS.get(key, FONTS["poppins"])
    path = FONT_DIR / (strong if bold else regular)
    try:
        font = ImageFont.truetype(str(path), size)
        if axes:
            font.set_variation_by_axes([axes[1] if bold else axes[0]])
        return font
    except (OSError, ValueError):
        return ImageFont.load_default(size)


def clean_text(text: str) -> str:
    """Quita emojis y marcas de Discord que Pillow no puede dibujar (saldrían como cuadros)."""
    text = re.sub(r"<a?:\w+:\d+>", "", text)  # emojis personalizados
    text = "".join(
        ch for ch in text
        if ord(ch) <= 0xFFFF and unicodedata.category(ch) not in ("So", "Cs", "Mn") or ch in "\n"
    )
    return re.sub(r"[ \t]+", " ", text).strip()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    lines: List[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            while draw.textlength(word, font=font) > max_width and len(word) > 1:  # palabra gigante
                cut = len(word)
                while cut > 1 and draw.textlength(word[:cut], font=font) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        lines.append(current)
    return lines


def _fit(draw, text, key, max_width, max_height, start=60, stop=28):
    """Tamaño de letra más grande con el que el texto cabe; si no cabe, lo recorta con '…'."""
    for size in range(start, stop - 1, -2):
        font = _font(key, size)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) * int(size * 1.28) <= max_height:
            return font, lines, size
    font = _font(key, stop)
    lines = _wrap(draw, text, font, max_width)
    limit = max(1, max_height // int(stop * 1.28))
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = lines[-1].rstrip(" .,;:") + "…"
    return font, lines, stop


def _avatar_layer(avatar: Optional[bytes], side: int, bg: Tuple[int, int, int], fade_axis: str) -> Image.Image:
    """Avatar en gris recortado a un cuadrado `side`, desvaneciéndose hacia el color de fondo."""
    if avatar:
        img = Image.open(io.BytesIO(avatar)).convert("L").resize((side, side), Image.LANCZOS)
    else:
        img = Image.new("L", (side, side), 60)
    rgb = Image.merge("RGB", (img, img, img))
    mask = Image.new("L", (side, side), 255)
    px = mask.load()
    start = int(side * 0.38)  # a partir de aquí empieza a desvanecerse
    for i in range(side):
        alpha = 255 if i < start else int(255 * max(0.0, 1 - (i - start) / (side - start)) ** 1.4)
        for j in range(side):
            if fade_axis == "x":
                px[i, j] = alpha
            else:
                px[j, i] = alpha
    base = Image.new("RGB", (side, side), bg)
    base.paste(rgb, (0, 0), mask)
    return base


def render_quote(
    avatar: Optional[bytes],
    text: str,
    name: str,
    handle: str,
    *,
    font: str = "poppins",
    theme: str = "white",
    layout: str = "wide",
) -> bytes:
    """Devuelve el PNG de la cita. `handle` va sin @."""
    colors = THEMES.get(theme, THEMES["white"])
    width, height = LAYOUTS.get(layout, LAYOUTS["wide"])["size"]
    text = clean_text(text) or "…"
    name = clean_text(name) or "usuario"

    canvas = Image.new("RGB", (width, height), colors["bg"])
    draw = ImageDraw.Draw(canvas)

    if layout == "wide":
        canvas.paste(_avatar_layer(avatar, height, colors["bg"], "x"), (0, 0))
        x0, x1 = 640, width - 70
        top, bottom = 70, height - 70
        align = "left"
    elif layout == "square":
        side = 520
        art = _avatar_layer(avatar, side, colors["bg"], "y")
        canvas.paste(art, ((width - side) // 2, 0))
        x0, x1 = 90, width - 90
        top, bottom = side - 40, height - 70
        align = "center"
    else:  # minimal
        x0, x1 = 100, width - 100
        top, bottom = 50, height - 50
        align = "center"

    quote_font = _font(font, 150, bold=True)
    sign_font = _font(font, 32, bold=True)
    handle_font = _font(font, 24)
    sign_h = 32 + 12 + 24 + 6
    quote_h = 70
    body_font, lines, size = _fit(draw, text, font, x1 - x0, bottom - top - sign_h - quote_h - 40)
    line_h = int(size * 1.28)
    block_h = quote_h + len(lines) * line_h + 28 + sign_h
    y = top + max(0, (bottom - top - block_h) // 2)

    def put(txt, fnt, color, y_pos):
        if align == "center":
            w = draw.textlength(txt, font=fnt)
            draw.text(((x0 + x1 - w) / 2, y_pos), txt, font=fnt, fill=color)
        else:
            draw.text((x0, y_pos), txt, font=fnt, fill=color)

    put("\u201c", quote_font, colors["quote"], y - 6)
    y += quote_h
    for line in lines:
        put(line, body_font, colors["text"], y)
        y += line_h
    y += 28
    put(f"\u2014 {name}", sign_font, colors["text"], y)
    put(f"@{handle}", handle_font, colors["muted"], y + 32 + 12)

    out = io.BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue()
