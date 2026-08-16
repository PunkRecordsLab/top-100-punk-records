"""Maps raw infobox fields -> the site's {name, ja, crew, aliases, img_source_url} shape."""
import re

_FORMER_RE = re.compile(r"\bformer\b|\bex-|\bdisbanded\b|\bdissolved\b", re.I)


def _find_label(raw_fields: dict, *keywords):
    """First label (in insertion/document order) containing ALL given keywords."""
    for label, values in raw_fields.items():
        if all(kw in label for kw in keywords):
            return values
    return None


def _first_label_containing_any(raw_fields: dict, *keywords):
    for label, values in raw_fields.items():
        if any(kw in label for kw in keywords):
            return values
    return None


def pick_ja(raw_fields: dict) -> str:
    values = _find_label(raw_fields, "japanese", "name")
    if not values:
        values = _first_label_containing_any(raw_fields, "japanese")
    return values[0] if values else ""


def pick_crew(raw_fields: dict) -> str:
    values = _first_label_containing_any(raw_fields, "affiliation", "owner", "crew")
    if not values:
        return ""
    for v in values:
        if not _FORMER_RE.search(v):
            return v
    return values[0]


def pick_aliases(raw_fields: dict) -> list:
    aliases = []
    for kw in ("epithet", "alias"):
        values = _first_label_containing_any(raw_fields, kw)
        if values:
            aliases.extend(values)
    # de-dupe, preserve order
    seen = set()
    out = []
    for a in aliases:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def map_to_character(raw_fields: dict, page_title: str, title_fallback: str, image_url) -> dict:
    name = title_fallback or page_title
    return {
        "name": name,
        "ja": pick_ja(raw_fields),
        "crew": pick_crew(raw_fields),
        "aliases": pick_aliases(raw_fields),
        "img_source_url": image_url,
    }
