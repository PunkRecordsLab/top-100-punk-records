"""Phase C: download + save character portrait images. Idempotent and
failure-tolerant -- a bad image never kills the character's other data,
it just falls back to img: null (the site's monogram-avatar default)."""
import io
import logging
import os

from PIL import Image, UnidentifiedImageError

from fetcher import BlockedError

logger = logging.getLogger("scraper.images")

MAX_DIMENSION = 600  # defensive cap even if the URL-based resize wasn't honored


def download_and_save(fetcher, image_url: str, dest_path: str, max_width: int = 400) -> bool:
    """Returns True on success (file written to dest_path), False on any failure."""
    try:
        resp = fetcher.get(image_url)
    except BlockedError:
        raise
    except Exception as exc:
        logger.warning("failed to download image %s: %s", image_url, exc)
        return False

    if resp.status_code != 200:
        logger.warning("image %s returned status %s", image_url, resp.status_code)
        return False

    content_type = resp.headers.get("Content-Type", "")
    if content_type and not content_type.startswith("image/"):
        logger.warning("image %s has non-image content-type %s", image_url, content_type)
        return False

    try:
        img = Image.open(io.BytesIO(resp.content))
        img.load()
    except UnidentifiedImageError:
        logger.warning("could not decode image at %s", image_url)
        return False

    if img.mode not in ("RGB",):
        img = img.convert("RGB")

    w, h = img.size
    longest = max(w, h)
    if longest > max(max_width, MAX_DIMENSION):
        scale = max(max_width, MAX_DIMENSION) / longest
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = dest_path + ".tmp"
    try:
        img.save(tmp_path, format="JPEG", quality=85, optimize=True)
        os.replace(tmp_path, dest_path)
    except Exception as exc:
        logger.warning("failed to save image to %s: %s", dest_path, exc)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False

    return True
