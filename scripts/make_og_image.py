"""Builds the social preview image - the picture Telegram, X and the rest
show when someone pastes a link to Unector.

Why this exists as a script rather than a file somebody exported once: the
image has to stay in step with the logo and the brand colours, and it is
1200x630 for a reason. Telegram falls back to a small square thumbnail
below that size, and the same 1.91:1 frame is what X, WhatsApp and Facebook
crop to without cutting anything off.

The format matters too. Telegram reads PNG and JPEG and does not reliably
render SVG or WebP, so the SVG logo the site uses cannot be pointed at
directly - it is rasterised here instead.

    python scripts/make_og_image.py

Writes frontend/public/og-image.png. Needs DM Sans, the brand face, which
is fetched alongside it - see FONT_DIR below.
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "frontend" / "public"
FONT_DIR = ROOT / ".ogbuild"
OUT = PUBLIC / "og-image.png"

# 1200x630 is the size every platform documents, and the one Telegram needs
# to show a large preview rather than a thumbnail.
WIDTH, HEIGHT = 1200, 630

# Straight from frontend/src/index.css - the dark theme's own values, so the
# card and the site look like the same product.
BG = "#161616"
TEXT = "#f5f4f0"
MUTED = "#8f8d86"
ACCENT = "#c3f832"

TITLE = "Unector"
TAGLINE = [
    "Dispatch management for trucking companies,",
    "run through Telegram.",
]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / name
    if not path.exists():
        sys.exit(
            f"{path} is missing. DM Sans is the brand face - the same one\n"
            "frontend/src/index.css imports from Google Fonts - and is a build\n"
            "input rather than something committed. Ask Google Fonts for the\n"
            "TTF URLs (an old user agent is what makes it serve TTF rather\n"
            "than woff2), then save the two files it names:\n\n"
            "  mkdir -p .ogbuild\n"
            "  curl -sA 'Mozilla/5.0 (Windows NT 6.1)' \\\n"
            "    'https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;700' \\\n"
            "    | grep -oE 'https://[^)]*[.]ttf'\n\n"
            "The first is .ogbuild/dmsans-regular.ttf, the second\n"
            ".ogbuild/dmsans-bold.ttf."
        )
    return ImageFont.truetype(str(path), size)


def logo(size: int) -> Image.Image:
    """The wordmark's SVG, rasterised.

    Rendered against the card's own background rather than transparency:
    reportlab's PNG backend has no alpha, and matching the background makes
    the seam invisible without needing one."""
    drawing = svg2rlg(str(PUBLIC / "logo-white.svg"))
    scale = size / drawing.width
    drawing.width *= scale
    drawing.height *= scale
    drawing.scale(scale, scale)
    return renderPM.drawToPIL(drawing, bg=int(BG[1:], 16)).convert("RGB")


def main() -> int:
    card = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(card)

    mark = logo(210)
    left = 96 + mark.width + 64

    title_font = font("dmsans-bold.ttf", 92)
    body_font = font("dmsans-regular.ttf", 34)

    # Measured rather than guessed. Hardcoded offsets put the accent rule
    # through the middle of the title the first time, and any change to the
    # face or the size would do it again.
    LINE_GAP = 46
    RULE_GAP = 30
    # textbbox is measured from the drawing origin, so box[1] is the gap
    # above the glyphs rather than part of them. The visible height is the
    # difference, and subtracting box[1] when drawing puts that visible top
    # exactly where the layout says it should be.
    box = draw.textbbox((0, 0), TITLE, font=title_font)
    title_height = box[3] - box[1]
    # The gap belongs *between* the tagline lines, so counting one per line
    # leaves a phantom line's worth of space under the last one and lifts
    # the whole block off centre.
    line_box = draw.textbbox((0, 0), TAGLINE[-1], font=body_font)
    body_height = LINE_GAP * (len(TAGLINE) - 1) + (line_box[3] - line_box[1])
    total = title_height + RULE_GAP + 5 + RULE_GAP + body_height
    top = (HEIGHT - total) // 2

    # The logo reads as part of the same block, so it centres on the block
    # rather than on the canvas.
    card.paste(mark, (96, top + (total - mark.height) // 2))

    draw.text((left, top - box[1]), TITLE, font=title_font, fill=TEXT)

    # A short rule in the brand accent. It separates the name from the
    # sentence without drawing attention to itself.
    rule_y = top + title_height + RULE_GAP
    draw.rectangle([left, rule_y, left + 72, rule_y + 5], fill=ACCENT)

    y = rule_y + 5 + RULE_GAP - line_box[1]
    for line in TAGLINE:
        draw.text((left, y), line, font=body_font, fill=MUTED)
        y += LINE_GAP

    # Ownership stamped into the file itself, the way the logo SVG carries
    # it, so the image can be identified wherever it ends up.
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Title", "Unector")
    meta.add_text("Author", "Unector LLC")
    meta.add_text("Copyright", "Unector LLC")
    meta.add_text("Description", "Social preview card for Unector")
    meta.add_text("Software", "scripts/make_og_image.py")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    card.save(OUT, "PNG", optimize=True, pnginfo=meta)

    kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT.relative_to(ROOT)}  {WIDTH}x{HEIGHT}  {kb:.0f} KB")
    if kb > 400:
        print("  Larger than the few hundred KB the platforms prefer - worth trimming.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
