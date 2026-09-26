"""Genera build/icon.ico, l'icona dell'eseguibile.

Riprende il marchio che sta nella barra dell'hub: tre righe di testo che si
accorciano (le stringhe da tradurre) e un punto ambra a destra. Disegnata a
256px e poi ridotta, con le proporzioni ritoccate alle misure piccole,
altrimenti a 16px le righe si impastano.

    python tools/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 24, 32, 48, 64, 128, 256)

BG_TOP = (30, 41, 54)
BG_BOTTOM = (13, 19, 26)
BAR = (223, 233, 243)
DOT = (255, 176, 32)


def draw_icon(size: int) -> Image.Image:
    # Si disegna 4x e si riduce: e' il modo piu' semplice per avere bordi
    # morbidi senza gestire l'antialiasing a mano.
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Fondo: quadrato con angoli arrotondati e sfumatura verticale.
    radius = int(s * 0.22)
    plate = Image.new("RGB", (s, s))
    pd = ImageDraw.Draw(plate)
    for y in range(s):
        t = y / max(s - 1, 1)
        pd.line(
            [(0, y), (s, y)],
            fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)),
        )
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius, fill=255)
    img.paste(plate, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # Alle misure piccole le righe vanno piu' spesse e piu' distanziate,
    # altrimenti si fondono in una macchia.
    piccolo = size <= 32
    h = s * (0.085 if piccolo else 0.072)
    gap = s * (0.135 if piccolo else 0.118)
    left = s * 0.17
    widths = (0.66, 0.46, 0.56) if piccolo else (0.62, 0.40, 0.52)
    top = s * 0.5 - (h * 3 + gap * 2) / 2

    for i, w in enumerate(widths):
        y = top + i * (h + gap)
        d.rounded_rectangle(
            [left, y, left + s * w, y + h], radius=h / 2, fill=BAR
        )

    # Il punto ambra: l'accento del marchio, sempre leggibile anche a 16px.
    r = s * (0.115 if piccolo else 0.10)
    cx, cy = s * 0.775, s * 0.5
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DOT)

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/icon.ico")
    dest.parent.mkdir(parents=True, exist_ok=True)

    frames = [draw_icon(n) for n in SIZES]
    # Il primo fotogramma porta con se' tutte le misure dentro il .ico.
    frames[-1].save(dest, format="ICO", sizes=[(n, n) for n in SIZES])

    anteprima = dest.with_suffix(".preview.png")
    strip = Image.new("RGBA", (sum(SIZES) + 10 * len(SIZES), 256), (11, 16, 21, 255))
    x = 0
    for f in frames:
        strip.paste(f, (x, (256 - f.height) // 2), f)
        x += f.width + 10
    strip.save(anteprima)

    print(f"scritto {dest} ({dest.stat().st_size / 1024:.1f} KB) con {len(SIZES)} misure")
    print(f"anteprima: {anteprima}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
