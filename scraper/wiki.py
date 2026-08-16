"""Shared constants/helpers for talking to the One Piece Fandom wiki.

IMPORTANT: plain https://onepiece.fandom.com/wiki/<Title> page fetches are
blocked (confirmed 403 from this network with an honest User-Agent). The
MediaWiki API at /api.php is NOT blocked and is used for everything --
both listing pages and fetching per-page rendered HTML (via action=parse).
"""
from urllib.parse import quote, unquote

API_URL = "https://onepiece.fandom.com/api.php"


def title_to_page_url(title: str) -> str:
    """Canonical, human-clickable URL used as the stable key for a page (for
    logging/debugging/state storage) -- never fetched directly, only via API."""
    return f"https://onepiece.fandom.com/wiki/{quote(title.replace(' ', '_'))}"


def page_url_to_title(page_url: str) -> str:
    tail = page_url.rsplit("/", 1)[-1]
    return unquote(tail).replace("_", " ")


def api_parse_url(title: str) -> str:
    return f"{API_URL}?action=parse&page={quote(title)}&format=json&prop=text"


def api_categorymembers_url(category_title: str, cmcontinue: str = None) -> str:
    url = (
        f"{API_URL}?action=query&list=categorymembers&cmtitle={quote(category_title)}"
        f"&cmlimit=500&format=json"
    )
    if cmcontinue:
        url += f"&cmcontinue={quote(cmcontinue)}"
    return url
