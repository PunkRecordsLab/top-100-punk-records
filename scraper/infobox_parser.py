"""Phase B: fetch one wiki page via the API and parse its Portable Infobox.

Ground truth observed directly against onepiece.fandom.com (via action=parse,
the plain /wiki/ route is blocked -- see wiki.py):
  - Infobox root: aside.portable-infobox
  - Each labeled row: div.pi-item.pi-data > .pi-data-label / .pi-data-value
  - Multi-value fields are inconsistent: sometimes <br>-separated (each
    entry followed by a literal ";" in the same text node), sometimes a
    single line with ";"-separated entries and no <br> at all (e.g. Vivi's
    Affiliations). Handle both by splitting on <br> (turned into "\n")
    AND ";" after stripping footnote <sup class="reference"> noise.
  - Portrait image: .pi-image-thumbnail, "src" is already a real absolute
    URL (server-rendered HTML via the API, no browser-side lazy-load to
    worry about) with an existing .../revision/latest/scale-to-width-down/N
    suffix that we rewrite to our own target width.
  - Some pages legitimately have no infobox (returns None -- caller marks
    the page as no_infobox rather than treating it as an error).
"""
import logging
import re

from bs4 import BeautifulSoup

from wiki import api_parse_url

logger = logging.getLogger("scraper.infobox_parser")

_SCALE_RE = re.compile(r"/revision/latest/scale-to-width-down/\d+")


def fetch_page_html(fetcher, page_title: str) -> str:
    resp = fetcher.get(api_parse_url(page_title))
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"API error parsing {page_title}: {data['error']}")
    return data["parse"]["text"]["*"]


def _clean_value_text(value_el) -> list:
    """Strip footnote <sup> noise, turn <br> into newlines, then split on
    both newline and ';' to get a list of clean individual entries."""
    el = value_el
    for sup in el.select("sup"):
        sup.decompose()
    for br in el.find_all("br"):
        br.replace_with("\n")
    raw = el.get_text()
    parts = re.split(r"[\n;]", raw)
    out = []
    for p in parts:
        p = p.strip().rstrip(";,").strip()
        if p:
            out.append(p)
    return out


def parse_infobox(html: str):
    """Returns (infobox_soup_or_None, raw_fields, title_fallback).
    raw_fields: {lowercased label (colon stripped): [value entries...]}"""
    soup = BeautifulSoup(html, "lxml")
    infobox = soup.select_one("aside.portable-infobox")
    if infobox is None:
        return None, {}, None

    title_el = infobox.select_one(".pi-item.pi-title, .pi-title")
    title_fallback = title_el.get_text(strip=True) if title_el else None
    # Fandom appends a "[v·e]" edit-link suffix to the infobox title; strip it.
    if title_fallback:
        title_fallback = re.sub(r"\[.*?\]\s*$", "", title_fallback).strip()

    raw_fields = {}
    for item in infobox.select("div.pi-item.pi-data"):
        label_el = item.select_one(".pi-data-label")
        value_el = item.select_one(".pi-data-value")
        if not label_el or not value_el:
            continue
        label = label_el.get_text(strip=True).rstrip(":").strip().lower()
        if not label:
            continue
        values = _clean_value_text(value_el)
        if not values:
            continue
        # First occurrence of a given label wins (the main character's own
        # fields always appear before any nested/transcluded sub-infobox,
        # e.g. a Devil Fruit panel embedded further down the same aside).
        raw_fields.setdefault(label, values)

    return infobox, raw_fields, title_fallback


def extract_image_url(infobox, width: int = 400):
    if infobox is None:
        return None
    img = infobox.select_one(".pi-image-thumbnail")
    if img is None:
        return None
    url = img.get("src") or img.get("data-src")
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    if _SCALE_RE.search(url):
        url = _SCALE_RE.sub(f"/revision/latest/scale-to-width-down/{width}", url)
    elif "/revision/latest" in url:
        url = url.replace("/revision/latest", f"/revision/latest/scale-to-width-down/{width}", 1)
    return url


def parse_character_page(fetcher, page_title: str, width: int = 400):
    """High-level entrypoint for Phase B: fetch + fully parse one page.
    Returns dict with keys: infobox_found, raw_fields, title_fallback, image_url.
    """
    html = fetch_page_html(fetcher, page_title)
    infobox, raw_fields, title_fallback = parse_infobox(html)
    if infobox is None:
        logger.warning("no infobox found on %s", page_title)
        return {"infobox_found": False, "raw_fields": {}, "title_fallback": None, "image_url": None}
    image_url = extract_image_url(infobox, width=width)
    return {
        "infobox_found": True,
        "raw_fields": raw_fields,
        "title_fallback": title_fallback,
        "image_url": image_url,
    }
