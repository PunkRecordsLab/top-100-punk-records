"""Exact port of the site's norm/slug/uniqueSlug JS functions.

JS source (enquete-punk-records.html):
  const norm = s => (s||"").normalize("NFD").replace(/[\\u0300-\\u036f]/g,"").toLowerCase();
  const slug = s => norm(s).replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
  function uniqueSlug(name){
    const base=slug(name)||"personagem";
    let id=base, n=2;
    while(CHARS.some(c=>c.id===id)){ id=base+"-"+n; n++; }
    return id;
  }
"""
import re
import unicodedata

_DIACRITICS_RE = re.compile(r"[̀-ͯ]")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def norm(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFD", s)
    s = _DIACRITICS_RE.sub("", s)
    return s.lower()


def slug(s: str) -> str:
    s = norm(s)
    s = _NON_ALNUM_RE.sub("-", s)
    return s.strip("-")


def unique_slug(name: str, existing_ids: set) -> str:
    base = slug(name) or "personagem"
    candidate = base
    n = 2
    while candidate in existing_ids:
        candidate = f"{base}-{n}"
        n += 1
    existing_ids.add(candidate)
    return candidate
