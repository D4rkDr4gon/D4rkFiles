"""wallpalette.py — saca un tema (las 11 claves de color de theme.json) de un wallpaper.

Sin dependencias fuera de PIL. La idea es respetar el design system ("Flat
Minimal", docs/design-system.md) y no copiar los colores tal cual:
- background: el oscuro más frecuente de la imagen, llevado a luminosidad ~12 %
  y poca saturación (una superficie, no un color).
- chip_*: rampa oscuro→claro mezclando background con foreground (7/14/21/28 %),
  como hex_blend() de theme-switch.sh.
- foreground: casi blanco con un toque del tono del fondo.
- primary: el color más vivo y presente; se aclara hasta tener contraste >= 4.5
  contra el fondo (se usa como relleno de estado y texto de foco).
- secondary: otro tono a más de 30° del primary (o el primary rotado).
- status_ok/warn/error: verde/ámbar/rojo con la saturación y luz del primary,
  así combinan con el resto pero siguen leyéndose como estado.
"""

from __future__ import annotations

import colorsys
from pathlib import Path

from PIL import Image, ImageDraw


def hx(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def from_hex(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def hls(h: float, l: float, s: float) -> tuple[float, float, float]:
    return colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))


def blend(a: str, b: str, t: float) -> str:
    ra, rb = from_hex(a), from_hex(b)
    return hx(tuple(x + (y - x) * t for x, y in zip(ra, rb)))  # type: ignore[arg-type]


def luminance(rgb: tuple[float, float, float]) -> float:
    def ch(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = map(ch, rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(from_hex(a)), luminance(from_hex(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def palette(path: str | Path, n: int = 16) -> list[tuple[float, tuple[float, float, float]]]:
    """[(proporción, (h, l, s))] de los n colores principales, del más presente al menos."""
    im = Image.open(path).convert("RGB")
    im.thumbnail((240, 240))
    q = im.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    counts = sorted(q.getcolors() or [], reverse=True)
    total = sum(c for c, _ in counts) or 1
    out = []
    for count, idx in counts:
        r, g, b = (pal[idx * 3 + i] / 255 for i in range(3))
        out.append((count / total, colorsys.rgb_to_hls(r, g, b)))
    return out


def hue_dist(a: float, b: float) -> float:
    d = abs(a - b) % 1.0
    return min(d, 1 - d) * 360


def theme_from(path: str | Path) -> dict:
    cols = palette(path)
    darks = [c for c in cols if c[1][1] < 0.35]
    bh, _, bs = (darks or cols)[0][1]
    background = hx(hls(bh, 0.12, min(bs * 0.6, 0.30)))
    foreground = hx(hls(bh, 0.88, min(bs * 0.4, 0.15)))

    # Vivo y presente: saturación × presencia (raíz, para que un acento chico cuente)
    vivid = sorted((c for c in cols if 0.25 < c[1][1] < 0.85 and c[1][2] > 0.18),
                   key=lambda c: c[1][2] * c[0] ** 0.35, reverse=True)
    if vivid:
        ph, pl, ps = vivid[0][1]
    else:   # imagen gris: acento azulado suave
        ph, pl, ps = (bh if bs > 0.1 else 0.6), 0.65, 0.45
    ps = max(0.45, min(ps, 0.85))
    pl = max(pl, 0.55)
    primary = hx(hls(ph, pl, ps))
    while contrast(primary, background) < 4.5 and pl < 0.85:
        pl += 0.03
        primary = hx(hls(ph, pl, ps))

    sec = next((c for c in vivid[1:] if hue_dist(c[1][0], ph) > 30), None)
    sh, sl, ss = (sec[1] if sec else (ph + 30 / 360, pl, ps))
    sl, ss = max(sl, 0.6), max(0.4, min(ss, 0.8))
    secondary = hx(hls(sh, sl, ss))
    while contrast(secondary, background) < 4.5 and sl < 0.88:
        sl += 0.03
        secondary = hx(hls(sh, sl, ss))

    st_s, st_l = max(0.45, min(ps, 0.7)), max(0.62, min(pl, 0.72))
    theme = {
        "primary": primary, "secondary": secondary, "background": background, "foreground": foreground,
        "chip_battery": blend(background, foreground, 0.07), "chip_bluetooth": blend(background, foreground, 0.14),
        "chip_wlan": blend(background, foreground, 0.21), "chip_audio": blend(background, foreground, 0.28),
        "status_ok": hx(hls(125 / 360, st_l, st_s)), "status_warn": hx(hls(40 / 360, st_l, st_s + 0.1)),
        "status_error": hx(hls(355 / 360, st_l - 0.04, st_s + 0.1)),
    }
    return theme


def write_preview(wallpaper: str | Path, theme: dict, out: str | Path) -> None:
    """preview.png para Settings → Themes: el wallpaper (1920×1080, recortado al
    centro) con una franja de la paleta abajo."""
    W, H = 1920, 1080
    im = Image.open(wallpaper).convert("RGB")
    scale = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    left, top = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((left, top, left + W, top + H))
    d = ImageDraw.Draw(im)
    keys = ["background", "chip_battery", "chip_bluetooth", "chip_wlan", "chip_audio", "foreground",
            "primary", "secondary", "status_ok", "status_warn", "status_error"]
    bar_h, pad = 90, 40
    d.rounded_rectangle((pad - 12, H - bar_h - pad - 12, W - pad + 12, H - pad + 12), radius=18,
                        fill=theme["background"])
    w = (W - 2 * pad) / len(keys)
    for i, k in enumerate(keys):
        d.rounded_rectangle((pad + i * w + 4, H - bar_h - pad, pad + (i + 1) * w - 4, H - pad), radius=10,
                            fill=theme[k])
    im.save(out)
