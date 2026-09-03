"""The card people see when a Freight Pilot link is pasted somewhere.

Telegram, X and the rest fetch the page with a crawler that does not run
JavaScript, so none of this can come from React - it has to be in the HTML
the server sends. Two things here are easy to break by accident and
invisible until someone shares a link:

  * The preview URLs are written relative in index.html and made absolute
    per request, because the host is a tunnel in development and a real
    domain later. If that rewriting stops happening, Telegram will not
    fetch a relative og:image at all and the card loses its picture.

  * twitter:card is what chooses between a large image and a small square
    thumbnail. Telegram honours it, and without it the preview is a
    thumbnail however large the image is.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"
OG_IMAGE = ROOT / "frontend" / "public" / "og-image.png"

needs_build = pytest.mark.skipif(
    not (DIST / "index.html").exists(),
    reason="frontend/dist is not built - run npm run build",
)


def meta(html: str, key: str) -> str | None:
    attr = "property" if key.startswith("og:") else "name"
    match = re.search(rf'{attr}="{re.escape(key)}"\s+content="([^"]*)"', html)
    return match.group(1) if match else None


# ------------------------------------------------------------------
# The image itself
# ------------------------------------------------------------------

def test_the_preview_image_exists_and_is_the_documented_size():
    """1200x630 is what every platform documents, and what Telegram needs
    before it will show a large preview instead of a thumbnail."""
    from PIL import Image

    assert OG_IMAGE.exists(), "run python scripts/make_og_image.py"
    with Image.open(OG_IMAGE) as img:
        assert (img.width, img.height) == (1200, 630)
        assert img.format == "PNG", "Telegram does not reliably render SVG or WebP"


def test_the_preview_image_is_small_enough_to_be_fetched():
    """The platforms want a few hundred KB, and Telegram refuses over 5 MB."""
    assert OG_IMAGE.stat().st_size < 400 * 1024


def test_the_preview_image_carries_its_ownership():
    from PIL import Image

    with Image.open(OG_IMAGE) as img:
        assert img.text.get("Author") == "Freight Pilot LLC"


# ------------------------------------------------------------------
# The tags
# ------------------------------------------------------------------

@needs_build
def test_the_card_names_the_product_not_the_host(client):
    """Without og:site_name the crawler falls back to the domain, so a
    tunnel made the card say "Trycloudflare" above the title."""
    html = client.get("/").text
    assert meta(html, "og:site_name") == "Freight Pilot"


@needs_build
def test_the_card_asks_for_a_large_image(client):
    html = client.get("/").text
    assert meta(html, "twitter:card") == "summary_large_image"


@needs_build
def test_every_tag_the_crawlers_read_is_present(client):
    html = client.get("/").text
    for key in (
        "og:type", "og:site_name", "og:title", "og:description", "og:url",
        "og:image", "og:image:width", "og:image:height",
        "twitter:card", "twitter:title", "twitter:description", "twitter:image",
    ):
        assert meta(html, key), f"{key} is missing from the served HTML"


@needs_build
def test_the_image_url_is_absolute_and_matches_the_host_asked(client):
    """The whole point of rewriting: a relative og:image is never fetched,
    and a hardcoded one goes stale the moment the tunnel restarts."""
    html = client.get("/").text
    image = meta(html, "og:image")
    assert image.startswith("http"), f"og:image is not absolute: {image}"
    assert image.endswith("/og-image.png")
    assert "testserver" in image, f"og:image does not use the request's host: {image}"

    assert meta(html, "twitter:image") == image
    assert meta(html, "og:url").startswith("http")


@needs_build
def test_the_url_it_points_at_actually_serves_the_image(client):
    response = client.get("/og-image.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


@needs_build
def test_a_deep_link_still_gets_the_tags(client):
    """People share /pages/pricing, not just the root. React Router serves
    those from the same index.html, so the card has to survive the path."""
    html = client.get("/pages/pricing").text
    assert meta(html, "og:site_name") == "Freight Pilot"
    assert meta(html, "og:image").startswith("http")


@needs_build
def test_the_description_says_what_the_product_does(client):
    html = client.get("/").text
    description = meta(html, "og:description")
    assert "dispatch" in description.lower()
    assert "telegram" in description.lower()
    # Long enough to be worth reading, short enough not to be cut off.
    assert 80 < len(description) < 300
