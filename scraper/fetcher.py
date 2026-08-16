"""Polite, rate-limited, resumable-friendly HTTP fetcher for the wiki scraper."""
import logging
import time

import requests

logger = logging.getLogger("scraper.fetcher")

DEFAULT_USER_AGENT = (
    "PunkRecordsLab-RosterBot/1.0 "
    "(one-time private fan-vote roster pull; "
    "+https://github.com/PunkRecordsLab/top-100-punk-records)"
)


class BlockedError(RuntimeError):
    """Raised when the remote site appears to be actively blocking us."""


class Fetcher:
    def __init__(
        self,
        rate_limit: float = 1.0,
        max_retries: int = 5,
        user_agent: str = DEFAULT_USER_AGENT,
        block_threshold: int = 3,
        timeout=(5, 20),
    ):
        self.rate_limit = rate_limit
        self.max_retries = max_retries
        self.timeout = timeout
        self.block_threshold = block_threshold
        self._consecutive_blocks = 0
        self._last_request_ts = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def _pace(self):
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.rate_limit - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.monotonic()

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET with pacing, retry/backoff on transient errors, and block detection.

        Raises BlockedError if the site appears to be actively blocking us
        (repeated 403/429) -- callers should let this propagate and abort
        the whole run, not retry through it.
        Raises the last exception if retries are exhausted on transient errors.
        """
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            self._pace()
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                backoff = min(60, 2**attempt)
                logger.warning(
                    "transient error fetching %s (attempt %d/%d): %s -- retrying in %ss",
                    url, attempt, self.max_retries, exc, backoff,
                )
                time.sleep(backoff)
                continue

            if resp.status_code in (403, 429):
                self._consecutive_blocks += 1
                retry_after = resp.headers.get("Retry-After")
                logger.warning(
                    "got %s from %s (consecutive blocks: %d/%d)",
                    resp.status_code, url, self._consecutive_blocks, self.block_threshold,
                )
                if self._consecutive_blocks >= self.block_threshold:
                    raise BlockedError(
                        f"Site appears to be blocking us ({self._consecutive_blocks} "
                        f"consecutive 403/429 responses). Progress is saved; "
                        f"back off and resume later."
                    )
                if retry_after:
                    try:
                        time.sleep(float(retry_after))
                    except ValueError:
                        time.sleep(10)
                else:
                    time.sleep(min(60, 2**attempt))
                continue

            self._consecutive_blocks = 0

            if 500 <= resp.status_code < 600:
                last_exc = requests.HTTPError(f"{resp.status_code} from {url}")
                backoff = min(60, 2**attempt)
                logger.warning(
                    "server error %s fetching %s (attempt %d/%d) -- retrying in %ss",
                    resp.status_code, url, attempt, self.max_retries, backoff,
                )
                time.sleep(backoff)
                continue

            return resp

        raise last_exc or RuntimeError(f"failed to fetch {url} after {self.max_retries} attempts")
