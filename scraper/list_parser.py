"""Phase A: discover the full list of (title, page_url, source) to scrape.

Two shapes of source:
- "table" pages (List_of_Canon_Characters, List_of_Non-Canon_Characters):
  fetched via the API's action=parse (the plain /wiki/ route is blocked),
  then the "Individuals" table.fandom-table is parsed for character links.
  A second "Groups" table exists on both pages and is deliberately skipped
  -- those are crews/organizations, not individual votable characters.
- "category" pages (Category:Pirate_Ships): enumerated via the
  categorymembers API action, paginated via cmcontinue.
"""
import logging

from bs4 import BeautifulSoup

from wiki import api_categorymembers_url, api_parse_url, title_to_page_url

logger = logging.getLogger("scraper.list_parser")


def _find_individuals_table(soup: BeautifulSoup):
    tables = soup.select("table.fandom-table")
    if not tables:
        return None
    for heading in soup.find_all(["h2", "h3"]):
        text = heading.get_text(strip=True).lower()
        if text.startswith("individuals"):
            nxt = heading.find_next("table", class_="fandom-table")
            if nxt is not None:
                return nxt
    # Fallback: first fandom-table on the page (both known source pages
    # happen to list Individuals before Groups).
    return tables[0]


def parse_table_page(fetcher, page_title: str, source: str):
    """Fetch `page_title` via the API and extract (name, page_url, source)
    tuples from its "Individuals" table."""
    resp = fetcher.get(api_parse_url(page_title))
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"API error parsing {page_title}: {data['error']}")
    html = data["parse"]["text"]["*"]
    soup = BeautifulSoup(html, "lxml")

    table = _find_individuals_table(soup)
    if table is None:
        raise RuntimeError(f"no fandom-table found on {page_title}")

    results = []
    seen = set()
    for tr in table.select("tr"):
        if tr.select_one("th"):
            continue  # header row
        link = None
        for a in tr.select('a[href^="/wiki/"]'):
            href = a.get("href", "")
            if ":" in href.split("/wiki/", 1)[-1]:
                continue  # skip File:/Category:/interwiki links
            link = a
            break
        if link is None:
            continue
        title = link.get("title") or link.get_text(strip=True)
        if not title:
            continue
        page_url = title_to_page_url(title)
        if page_url in seen:
            continue
        seen.add(page_url)
        results.append((title, page_url, source))

    logger.info("parsed %d individuals from %s", len(results), page_title)
    return results


def _category_members_page(fetcher, category_title: str, cmcontinue=None):
    """One raw categorymembers page: returns (page_members, subcategory_titles, next_cmcontinue)."""
    resp = fetcher.get(api_categorymembers_url(category_title, cmcontinue))
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"API error listing {category_title}: {data['error']}")
    members = data.get("query", {}).get("categorymembers", [])
    pages = [m["title"] for m in members if m.get("ns") == 0]
    subcats = [m["title"] for m in members if m.get("ns") == 14]
    return pages, subcats, data.get("continue", {}).get("cmcontinue")


def parse_category(fetcher, category_title: str, source: str, max_depth: int = 4):
    """Enumerate all main-namespace members of a category via the API,
    paginating with cmcontinue and recursing into subcategories (many wikis,
    including this one, nest most real pages under subcategories rather
    than listing them directly -- e.g. Category:Pirate_Ships itself has
    only ~15 direct members, the rest live under per-crew subcategories)."""
    results = []
    seen_pages = set()
    visited_cats = set()
    queue = [(category_title, 0)]

    while queue:
        cat, depth = queue.pop(0)
        if cat in visited_cats:
            continue
        visited_cats.add(cat)

        cmcontinue = None
        while True:
            pages, subcats, cmcontinue = _category_members_page(fetcher, cat, cmcontinue)
            for title in pages:
                page_url = title_to_page_url(title)
                if page_url in seen_pages:
                    continue
                seen_pages.add(page_url)
                results.append((title, page_url, source))
            if depth < max_depth:
                for sc in subcats:
                    if sc not in visited_cats:
                        queue.append((sc, depth + 1))
            if not cmcontinue:
                break

    logger.info(
        "parsed %d members from category %s (%d subcategories visited)",
        len(results), category_title, len(visited_cats) - 1,
    )
    return results


# The three sources agreed in the plan.
SOURCES = [
    ("table", "List_of_Canon_Characters", "canon"),
    ("table", "List_of_Non-Canon_Characters", "non_canon"),
    ("category", "Category:Pirate_Ships", "ship"),
]


def discover_all(fetcher):
    """Run all three sources, return a combined deduped list of
    (title, page_url, source)."""
    combined = []
    seen = set()
    for kind, page_title, source in SOURCES:
        if kind == "table":
            items = parse_table_page(fetcher, page_title, source)
        else:
            items = parse_category(fetcher, page_title, source)
        for title, page_url, src in items:
            if page_url in seen:
                continue
            seen.add(page_url)
            combined.append((title, page_url, src))
    logger.info("discovered %d unique pages across all sources", len(combined))
    return combined
