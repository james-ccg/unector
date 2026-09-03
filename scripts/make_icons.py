"""Builds the raster icons that favicon.svg cannot cover on its own.

The SVG favicon is the good one: it is sharp at every size and it flips
between a dark and a light mark with the browser's theme, which no raster
format can do. It is also only understood by about 95% of browsers. Safari
ignores it and quietly falls back to favicon.ico, and iOS wants an
apple-touch-icon for the home screen - so without these files those users
get no icon at all.

    python scripts/make_icons.py

Writes into frontend/public:

  favicon.ico          16/32/48, the fallback Safari and older browsers use
  apple-touch-icon.png 180x180, iOS home screen
  icon-512.png         512x512, Android home screen and PWA installs

All three are drawn on the brand's dark background rather than left
transparent, for two reasons. iOS does not support transparency in a touch
icon - it fills the gaps with black, which turns a careful mark into a
smudge. And a raster icon cannot follow the browser theme the way the SVG
does, so a transparent dark mark would vanish on a dark tab bar; a solid
tile reads the same on both.

Corners are left square on purpose: iOS and Android round them themselves,
and rounding them here would round them twice.
"""
from __future__ import annotations

import pathlib
import re

from PIL import Image, ImageChops
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "frontend" / "public"
SOURCE = PUBLIC / "favicon.svg"
BUILD = ROOT / ".ogbuild"

# frontend/src/index.css's dark background, the same tile the social card uses.
BG = "#161616"
MARK = "#ffffff"

# The mark sits at 76% of the tile. Apple's own guidance leaves a margin, and
# a mark run to the edge looks cramped once the corners are rounded.
INSET = 0.76

# Android may crop a maskable icon to any shape it likes, and only promises
# to keep a circle of radius 40% of the width. The mark is landscape, so at
# 76% its corners land 237px from the centre of a 512px tile against a safe
# radius of 205 - outside, and clipped on a round mask. 58% brings the whole
# thing inside with room to spare.
#
# It is a separate file rather than the same one declared "any maskable":
# that combination makes a browser use one image for both, and an icon
# padded for the mask looks small everywhere it is not being masked.
MASKABLE_INSET = 0.58


def mark(size: int) -> Image.Image:
    """favicon.svg rasterised with the light-on-dark colours.

    The SVG picks its colour from a prefers-color-scheme rule, which a
    renderer has no theme to answer. The fill is applied here instead, so
    what comes out is the dark-theme version of the same artwork."""
    svg = re.sub(r"<style.*?</style>", "", SOURCE.read_text(encoding="utf-8"), flags=re.DOTALL)
    svg = re.sub(r"<path(?![^>]*fill=)", f'<path fill="{MARK}"', svg)

    BUILD.mkdir(parents=True, exist_ok=True)
    staged = BUILD / "_icon.svg"
    staged.write_text(svg, encoding="utf-8")

    drawing = svg2rlg(str(staged))
    scale = size / drawing.width
    drawing.width *= scale
    drawing.height *= scale
    drawing.scale(scale, scale)
    return renderPM.drawToPIL(drawing, bg=int(BG[1:], 16)).convert("RGB")


def trimmed(size: int) -> Image.Image:
    """The mark with the empty margin around it removed.

    The artwork does not sit centred inside its own viewBox, so centring the
    rendered square leaves the truck visibly off to one side. Cropping to
    the pixels that are actually drawn and centring that instead is what
    makes it look centred, which is the only thing that matters at 16px."""
    drawn = mark(size)
    ink = Image.new("RGB", drawn.size, BG)
    box = ImageChops.difference(drawn, ink).convert("L").getbbox()
    return drawn.crop(box) if box else drawn


def tile(size: int, inset: float = INSET) -> Image.Image:
    """One square icon: the mark, inset, centred on the brand background."""
    canvas = Image.new("RGB", (size, size), BG)

    inner = trimmed(size)
    room = round(size * inset)
    scale = min(room / inner.width, room / inner.height)
    inner = inner.resize(
        (max(1, round(inner.width * scale)), max(1, round(inner.height * scale))),
        Image.LANCZOS,
    )

    canvas.paste(inner, ((size - inner.width) // 2, (size - inner.height) // 2))
    return canvas


def main() -> int:
    # Rendered once at a size that divides down cleanly for every output.
    master = tile(512)

    ico = PUBLIC / "favicon.ico"
    master.save(ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])

    touch = PUBLIC / "apple-touch-icon.png"
    master.resize((180, 180), Image.LANCZOS).save(touch, "PNG", optimize=True)

    large = PUBLIC / "icon-512.png"
    master.save(large, "PNG", optimize=True)

    # The manifest wants a 192 as well as a 512, and Android picks whichever
    # is closest rather than scaling the big one well.
    small = PUBLIC / "icon-192.png"
    master.resize((192, 192), Image.LANCZOS).save(small, "PNG", optimize=True)

    maskable = PUBLIC / "icon-maskable-512.png"
    tile(512, MASKABLE_INSET).save(maskable, "PNG", optimize=True)

    for path in (ico, touch, large, small, maskable):
        print(f"Wrote {path.relative_to(ROOT)}  {path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
