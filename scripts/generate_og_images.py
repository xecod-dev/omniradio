#!/usr/bin/env python3
"""
Generate 1200x630 OG share-card PNGs for every station in config/stations.json.

Output: static/og/<station_id>.png
Fonts: Noto Kufi Arabic (Bold) + Noto Color Emoji (PIL RAQM must be enabled).
Brand palette mirrors the dark-emerald/gold theme of the player pages.
"""
import json
import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, features
except ImportError:
    sys.exit("Pillow is required: pip install pillow")

if not features.check("raqm"):
    sys.exit("PIL needs RAQM for correct Arabic shaping (pip install pillow[raqm])")

REPO = Path(__file__).resolve().parent.parent
STATIONS = json.loads((REPO / "config" / "stations.json").read_text(encoding="utf-8"))
if isinstance(STATIONS, dict):
    STATIONS = STATIONS.get("stations", [])

OUT_DIR = REPO / "static" / "og"
OUT_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1200, 630

FONT_AR = "/usr/share/fonts/truetype/noto/NotoKufiArabic-Bold.ttf"
FONT_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
FONT_EN = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Brand palette (same as --theme-bg1/bg2/accent)
BG1 = (6, 78, 59)     # #064e3b deep emerald
BG2 = (2, 44, 34)     # #022c22 near-black emerald
GOLD = (245, 158, 11) # #f59e0b amber
GOLD_SOFT = (251, 191, 36)  # #fbbf24
CREAM = (236, 253, 245)     # #ecfdf5
MUTED = (167, 243, 208)     # #a7f3d0


def vertical_gradient(w, h, top, bottom):
    base = Image.new("RGB", (w, h), top)
    overlay = Image.new("RGB", (w, h), bottom)
    mask = Image.new("L", (w, h))
    mask_data = []
    for y in range(h):
        mask_data.extend([int(255 * (y / h))] * w)
    mask.putdata(mask_data)
    return Image.composite(base, overlay, mask)


def load_emoji_font(size):
    return ImageFont.truetype(FONT_EMOJI, size)


def draw_ornament(draw):
    """Subtle gold 8-pointed star (Rub el Hizb) in the corner — drawn manually."""
    cx, cy, r = W - 120, 120, 52
    for box_r, width in ((r, 2), (r * 0.62, 2)):
        draw.ellipse([cx - box_r, cy - box_r, cx + box_r, cy + box_r],
                     outline=(*GOLD_SOFT, 70), width=width)
    half = r * 0.72
    draw.rectangle([cx - half, cy - half, cx + half, cy + half],
                   outline=(*GOLD_SOFT, 70), width=2)
    # rotated square is drawn as a diamond via polygon
    draw.polygon([(cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)],
                 outline=(*GOLD_SOFT, 70))
    draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(*GOLD_SOFT, 90))


def make_card(station):
    sid = station["id"]
    name = station.get("name", sid)
    name_en = station.get("name_en", "") or sid
    icon = station.get("icon", "📻") or "📻"
    category = station.get("category", "Quran") or "Quran"
    desc = station.get("description", "") or ""

    img = vertical_gradient(W, H, BG1, BG2).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    draw_ornament(draw)

    # Top-left brand mark (mimics header): small "OmniRadio"
    en_small = ImageFont.truetype(FONT_EN, 30)
    draw.text((56, 44), "OmniRadio  •  24/7 Live", font=en_small, fill=(*MUTED, 235))

    # Gold divider under brand
    draw.rectangle([56, 92, 340, 95], fill=(*GOLD, 200))

    # Station icon (color emoji) centered upper area.
    # NotoColorEmoji is a bitmap font: render at its native 109px, then upscale.
    emoji = load_emoji_font(109)
    bbox = draw.textbbox((0, 0), icon, font=emoji)
    iw, ih = bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _has_emoji_font():  # some icons are plain text glyphs (e.g. '📻' not in text fonts)
        try:
            emoji.getmask(icon)
            return True
        except Exception:
            return False

    if _has_emoji_font():
        icon_tmp = Image.new("RGBA", (max(iw + 8, 4), max(ih + 8, 4)), (0, 0, 0, 0))
        ImageDraw.Draw(icon_tmp).text((4 - bbox[0], 4 - bbox[1]), icon, font=emoji, embedded_color=True)
        scale = 140 / max(icon_tmp.size)
        icon_tmp = icon_tmp.resize((int(icon_tmp.width * scale), int(icon_tmp.height * scale)), Image.LANCZOS)
        img.paste(icon_tmp, (int((W - icon_tmp.width) / 2), 118), icon_tmp)

    # Station name (Arabic, bold, gold)
    font_name = ImageFont.truetype(FONT_AR, 74)
    bbox = draw.textbbox((0, 0), name, font=font_name)
    nw = bbox[2] - bbox[0]
    draw.text(((W - nw) / 2, 262), name, font=font_name, fill=(*GOLD_SOFT, 255))

    # English station name
    en_mid = ImageFont.truetype(FONT_EN, 38)
    if name_en:
        bbox = draw.textbbox((0, 0), name_en, font=en_mid)
        ew = bbox[2] - bbox[0]
        draw.text(((W - ew) / 2, 360), name_en, font=en_mid, fill=(*CREAM, 220))

    # Description line (Arabic, wrap-safe; keep short)
    line_font = ImageFont.truetype(FONT_AR, 34)
    tag = (desc if desc else f"بث مباشر • {category}")
    if len(tag) > 60:
        tag = tag[:60] + "…"
    bbox = draw.textbbox((0, 0), tag, font=line_font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) / 2, 440), tag, font=line_font, fill=(*MUTED, 235))

    # Footer stream URL
    url_font = ImageFont.truetype(FONT_EN, 30)
    url = "radio.xecod.com"
    bbox = draw.textbbox((0, 0), url, font=url_font)
    uw = bbox[2] - bbox[0]
    draw.text(((W - uw) / 2, 542), url, font=url_font, fill=(*GOLD, 200))

    out = OUT_DIR / f"{sid}.png"
    img.convert("RGB").save(out, "PNG")
    print(f"  {sid:20s} -> {out.relative_to(REPO)}")


def main():
    if not FONT_AR or not os.path.exists(FONT_AR):
        sys.exit(f"Arabic font not found: {FONT_AR}")
    if not os.path.exists(FONT_EMOJI):
        sys.exit(f"Emoji font not found: {FONT_EMOJI}")
    print(f"Generating {len(STATIONS)} OG cards into {OUT_DIR}/")
    for s in STATIONS:
        make_card(s)
    print("Done.")


if __name__ == "__main__":
    main()