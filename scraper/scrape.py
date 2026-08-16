#!/usr/bin/env python3
"""CLI orchestration for the Punk Records roster scraper.

Usage:
  python scrape.py list
  python scrape.py run --limit 25
  python scrape.py run --resume
  python scrape.py run --refetch-all
  python scrape.py build
  python scrape.py status
"""
import argparse
import logging
import os
import sys

import build_output
import images as images_mod
import list_parser
import mapper
import state as state_mod
import wiki
from fetcher import DEFAULT_USER_AGENT, BlockedError, Fetcher
from infobox_parser import parse_character_page
from slugify import slug

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRAPER_DIR)
DEFAULT_DB = os.path.join(SCRAPER_DIR, "state", "scrape_progress.sqlite3")
DEFAULT_LOG = os.path.join(SCRAPER_DIR, "state", "scrape.log")
DEFAULT_IMAGES_DIR = os.path.join(REPO_ROOT, "images")
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, "characters.json")


def setup_logging(log_path: str):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Force UTF-8 to stdout regardless of the Windows console's active code
    # page -- character names/aliases are frequently Japanese and a bare
    # print()/StreamHandler under cp1252 will crash mid-run otherwise.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def add_common_args(p: argparse.ArgumentParser):
    p.add_argument("--state-db", default=DEFAULT_DB)
    p.add_argument("--rate-limit", type=float, default=1.0)
    p.add_argument("--max-retries", type=int, default=5)
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)


def cmd_list(args):
    fetcher = Fetcher(rate_limit=args.rate_limit, max_retries=args.max_retries, user_agent=args.user_agent)
    conn = state_mod.connect(args.state_db)
    items = list_parser.discover_all(fetcher)
    n_new = state_mod.add_pages(conn, items)
    print(f"discovered {len(items)} pages total ({n_new} new since last run)")


def cmd_run(args):
    fetcher = Fetcher(rate_limit=args.rate_limit, max_retries=args.max_retries, user_agent=args.user_agent)
    conn = state_mod.connect(args.state_db)

    items = list_parser.discover_all(fetcher)
    n_new = state_mod.add_pages(conn, items)
    logging.info("phase A: %d pages known total, %d newly discovered", len(items), n_new)

    if args.refetch_all:
        state_mod.reset_pages(conn)
        logging.info("--refetch-all: reset all non-pending pages back to pending")

    pending = state_mod.get_pending_pages(conn, max_attempts=args.max_retries, limit=args.limit)
    logging.info("phase B/C: %d pages to process this invocation", len(pending))

    os.makedirs(args.images_dir, exist_ok=True)
    processed = 0
    no_infobox = 0
    errors = 0
    images_ok = 0
    images_failed = 0

    try:
        for page_url, page_title in pending:
            api_title = wiki.page_url_to_title(page_url)
            try:
                result = parse_character_page(fetcher, api_title, width=args.image_width)
            except BlockedError:
                raise
            except Exception as exc:
                logging.error("error processing %s: %s", page_title, exc)
                state_mod.mark_page_error(conn, page_url, str(exc))
                errors += 1
                continue

            if not result["infobox_found"]:
                state_mod.mark_page_no_infobox(conn, page_url)
                no_infobox += 1
                continue

            mapped = mapper.map_to_character(
                result["raw_fields"], page_title, result["title_fallback"], result["image_url"]
            )
            state_mod.upsert_character(conn, page_url, mapped)

            if not args.no_images and mapped["img_source_url"]:
                image_key = slug(page_title) or slug(mapped["name"]) or "personagem"
                dest = os.path.join(args.images_dir, f"{image_key}.jpg")
                try:
                    ok = images_mod.download_and_save(
                        fetcher, mapped["img_source_url"], dest, max_width=args.image_width
                    )
                except BlockedError:
                    raise
                if ok:
                    state_mod.update_image_status(conn, page_url, "done", dest)
                    images_ok += 1
                else:
                    state_mod.update_image_status(conn, page_url, "failed", None)
                    images_failed += 1
            else:
                state_mod.update_image_status(conn, page_url, "no_image", None)

            state_mod.mark_page_done(conn, page_url)
            processed += 1
            if processed % 25 == 0:
                logging.info("... %d/%d processed this run", processed, len(pending))

    except BlockedError as exc:
        logging.error("ABORTING RUN (site appears to be blocking us): %s", exc)
        print(f"\nStopped early -- {exc}")
        print("Progress is saved. Re-run with --resume later to continue.")
        return 1

    logging.info(
        "run finished: %d done, %d no_infobox, %d errors, %d images ok, %d images failed",
        processed, no_infobox, errors, images_ok, images_failed,
    )
    print(state_mod.status_summary(conn))
    return 0


def cmd_build(args):
    conn = state_mod.connect(args.state_db)
    result = build_output.build(conn, args.output, images_dir_name=os.path.basename(args.images_dir))
    print(result)


def cmd_status(args):
    conn = state_mod.connect(args.state_db)
    print(state_mod.status_summary(conn))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Phase A only: discover/refresh the page list")
    add_common_args(p_list)
    p_list.set_defaults(func=cmd_list)

    p_run = sub.add_parser("run", help="Discover + process pending pages (metadata + images)")
    add_common_args(p_run)
    p_run.add_argument("--limit", type=int, default=None, help="cap on newly-processed pages this invocation")
    p_run.add_argument("--refetch-all", action="store_true", help="reset all pages to pending before running")
    p_run.add_argument("--images-dir", default=DEFAULT_IMAGES_DIR)
    p_run.add_argument("--image-width", type=int, default=400)
    p_run.add_argument("--no-images", action="store_true", help="metadata-only run, skip image download")
    p_run.set_defaults(func=cmd_run)

    p_build = sub.add_parser("build", help="Phase D only: state DB -> characters.json (no network)")
    p_build.add_argument("--state-db", default=DEFAULT_DB)
    p_build.add_argument("--output", default=DEFAULT_OUTPUT)
    p_build.add_argument("--images-dir", default=DEFAULT_IMAGES_DIR)
    p_build.set_defaults(func=cmd_build)

    p_status = sub.add_parser("status", help="Print progress summary")
    p_status.add_argument("--state-db", default=DEFAULT_DB)
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    setup_logging(getattr(args, "log", DEFAULT_LOG) if hasattr(args, "log") else DEFAULT_LOG)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
