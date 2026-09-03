"""The site's icons, and the reasons each one exists.

The SVG favicon is the good one - sharp at any size, and it flips between a
dark and a light mark with the browser's theme, which no raster format can
do. It is also only understood by about 95% of browsers: Safari ignores it
and falls back to favicon.ico, and iOS wants an apple-touch-icon for the
home screen. Without those two that share of visitors gets no icon at all,
which is invisible from a development machine running Chrome.

Two properties here are easy to lose by accident. The theme rule lives
inside favicon.svg and would go the moment anyone re-exported the logo from
a design tool. And the touch icon has to be opaque, because iOS fills
transparency with black rather than leaving it clear.
"""
import pathlib
import re

import pytest
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "frontend" / "public"
INDEX = ROOT / "frontend" / "index.html"


# ------------------------------------------------------------------
# The SVG, and the rule that makes it follow the browser
# ------------------------------------------------------------------

def test_the_svg_favicon_still_follows_the_browser_theme():
    """A near-black mark is invisible on a dark tab bar and a white one is
    invisible on a light one. The media query inside the file is what
    stops either happening, and re-exporting the logo would drop it."""
    svg = (PUBLIC / "favicon.svg").read_text(encoding="utf-8")
    assert "prefers-color-scheme" in svg
    assert re.search(r"path:not\(\[fill\]\)\s*\{\s*fill:\s*#111", svg), "no light-theme colour"
    assert re.search(r"prefers-color-scheme:\s*dark\).*fill:\s*#fff", svg, re.DOTALL), (
        "no dark-theme colour"
    )


# ------------------------------------------------------------------
# The raster fallbacks
# ------------------------------------------------------------------

def test_there_is_an_ico_for_the_browsers_that_ignore_svg():
    ico = PUBLIC / "favicon.ico"
    assert ico.exists(), "run python scripts/make_icons.py"
    with Image.open(ico) as img:
        sizes = {size for size in img.info.get("sizes", set())}
    assert {(16, 16), (32, 32), (48, 48)} <= sizes, f"only {sorted(sizes)}"


def test_the_touch_icon_is_the_size_ios_asks_for():
    with Image.open(PUBLIC / "apple-touch-icon.png") as img:
        assert (img.width, img.height) == (180, 180)


def test_the_touch_icon_is_opaque():
    """iOS does not honour transparency in a touch icon - it fills the gaps
    with black, which turns a careful mark into a smudge. Being opaque
    already is what makes that a non-event."""
    with Image.open(PUBLIC / "apple-touch-icon.png") as img:
        assert img.mode == "RGB", f"has an alpha channel ({img.mode})"


def test_there_is_a_large_icon_for_android_and_installs():
    with Image.open(PUBLIC / "icon-512.png") as img:
        assert (img.width, img.height) == (512, 512)


@pytest.mark.parametrize("name", ["favicon.ico", "apple-touch-icon.png", "icon-512.png"])
def test_the_icons_are_small_enough_not_to_matter(name):
    assert (PUBLIC / name).stat().st_size < 100 * 1024


def test_the_mark_is_centred_on_its_tile():
    """The artwork does not sit centred inside its own viewBox, so the tile
    is built around the pixels actually drawn. Getting that wrong is only
    obvious at 16px, by which point nobody is looking."""
    from PIL import ImageChops

    with Image.open(PUBLIC / "icon-512.png") as img:
        icon = img.convert("RGB")
    background = Image.new("RGB", icon.size, icon.getpixel((0, 0)))
    left, top, right, bottom = ImageChops.difference(icon, background).convert("L").getbbox()

    assert abs(left - (icon.width - right)) <= 2, "off centre horizontally"
    assert abs(top - (icon.height - bottom)) <= 2, "off centre vertically"


# ------------------------------------------------------------------
# Declaring them
# ------------------------------------------------------------------

def test_the_page_offers_all_three_to_the_browser():
    html = INDEX.read_text(encoding="utf-8")
    assert 'href="/favicon.ico"' in html
    assert 'href="/favicon.svg"' in html
    assert 'rel="apple-touch-icon"' in html
