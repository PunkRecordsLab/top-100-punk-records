"""Phase D: read the state DB -> write the final characters.json.

Network-free, fast, idempotent -- safe to run any time against whatever is
currently in the state DB, even mid-scrape, to get a partial-but-valid
roster for early testing.

Final `id` assignment happens HERE (not during Phase B) so collision
resolution (-2, -3...) is stable and reproducible regardless of which
pages happened to be (re)fetched in which order -- see slugify.unique_slug.
"""
import json
import logging
import os

import state as state_mod
from slugify import unique_slug

logger = logging.getLogger("scraper.build_output")


def build(conn, output_path: str, images_dir_name: str = "images"):
    rows = state_mod.all_done_characters(conn)
    existing_ids = set()
    characters = []
    skipped_no_name = 0

    for page_url, name, ja, crew, aliases_json, img_local_path in rows:
        if not name or not name.strip():
            skipped_no_name += 1
            continue
        cid = unique_slug(name, existing_ids)
        aliases = json.loads(aliases_json) if aliases_json else []
        img = None
        if img_local_path:
            img = os.path.basename(img_local_path)
        characters.append(
            {
                "id": cid,
                "name": name,
                "ja": ja or "",
                "crew": crew or "",
                "aliases": aliases,
                "img": img,
            }
        )

    ids = [c["id"] for c in characters]
    assert len(ids) == len(set(ids)), "duplicate ids slipped through unique_slug"

    empty_crew = sum(1 for c in characters if not c["crew"])
    empty_ja = sum(1 for c in characters if not c["ja"])
    no_image = sum(1 for c in characters if not c["img"])

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(characters, f, ensure_ascii=False, indent=1)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)

    logger.info("wrote %d characters to %s (%.2f MB)", len(characters), output_path, size_mb)
    if skipped_no_name:
        logger.warning("skipped %d rows with empty name", skipped_no_name)
    logger.info(
        "coverage: %d/%d missing crew, %d/%d missing ja, %d/%d missing image",
        empty_crew, len(characters), empty_ja, len(characters), no_image, len(characters),
    )
    if size_mb > 4.5:
        logger.warning(
            "output is %.2f MB, close to the site's ~5MB per-storage-key limit!", size_mb
        )

    return {
        "count": len(characters),
        "size_mb": size_mb,
        "empty_crew": empty_crew,
        "empty_ja": empty_ja,
        "no_image": no_image,
        "skipped_no_name": skipped_no_name,
    }
