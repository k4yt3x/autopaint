import random
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import requests
from loguru import logger

from autopaint.ratelimit import AdaptiveRateLimiter
from autopaint.useragent import build_extra_headers

if TYPE_CHECKING:
    from autopaint.monitor import RankGate

VOTE_URL_TEMPLATE = "https://please.paintastreet.com/tiles/{tile_id}/vote"

DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Referer": "https://paintastreet.com/",
    "content-type": "application/json",
    "Origin": "https://paintastreet.com",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

FALLBACK_WAIT_SECONDS = 600
TILE_BACKOFF_MIN_SECONDS = 10
TILE_BACKOFF_MAX_SECONDS = 60


class ActiveVoterTracker:
    """Track how many voters are actively voting vs waiting on session cooldown.

    When all voters are on cooldown, a warning is printed to tell the user
    that more sessions are needed to maintain voting throughput.
    """

    def __init__(self, total: int) -> None:
        self._total = total
        self._active = total
        self._lock = threading.Lock()
        self._warned = False

    def enter_cooldown(self) -> None:
        with self._lock:
            self._active -= 1

            if self._active == 0 and not self._warned:
                self._warned = True
                logger.warning(
                    "All {} sessions are on cooldown — "
                    "add more sessions to maintain continuous voting",
                    self._total,
                )

    def leave_cooldown(self) -> None:
        with self._lock:
            self._active += 1
            self._warned = False


class Voter:
    def __init__(
        self,
        index: int,
        session_cookie: str,
        user_agent: str,
        tile_id: str,
        proxy: str | None = None,
        gate: RankGate | None = None,
        limiter: AdaptiveRateLimiter | None = None,
        tracker: ActiveVoterTracker | None = None,
    ) -> None:
        self.session_cookie = session_cookie
        self.tile_id = tile_id
        self.url = VOTE_URL_TEMPLATE.format(tile_id=tile_id)

        self.headers = {
            **DEFAULT_HEADERS,
            **build_extra_headers(user_agent),
            "User-Agent": user_agent,
            "Cookie": f"session={session_cookie}",
        }

        self.proxies = {"https": proxy} if proxy else None
        self.gate = gate
        self.limiter = limiter
        self.tracker = tracker
        self.label = f"#{index:02d} {session_cookie[:8]}"

    def _cast_vote(self) -> requests.Response:
        return requests.put(
            self.url,
            headers=self.headers,
            json={"direction": "up"},
            proxies=self.proxies,
            timeout=30,
        )

    def _get_wait_seconds(self, body: dict) -> float:
        """Determine how long to wait based on the response body."""
        budget = body.get("vote_budget", {})
        reset_at = budget.get("reset_at")

        if reset_at:
            try:
                reset_time = datetime.fromisoformat(reset_at)
                now = datetime.now(timezone.utc)
                wait = (reset_time - now).total_seconds() + 1
                if wait > 0:
                    return wait
            except ValueError, TypeError:
                pass

        window = budget.get("window_seconds")
        if window:
            return int(window) + 1

        return FALLBACK_WAIT_SECONDS

    def _wait_until_reset(self, body: dict) -> None:
        """Sleep until the vote budget resets based on the response body."""
        wait = self._get_wait_seconds(body)
        logger.info("[{}] Waiting {:.0f}s until reset", self.label, wait)

        if self.tracker is not None:
            self.tracker.enter_cooldown()

        time.sleep(wait)

        if self.tracker is not None:
            self.tracker.leave_cooldown()

    def run(self) -> None:
        """Vote in a loop, respecting rate limits. Runs forever."""
        logger.info("[{}] Starting voter", self.label)
        logger.debug("[{}] UA: {}", self.label, self.headers["User-Agent"])
        logger.debug(
            "[{}] Proxy: {}",
            self.label,
            self.proxies.get("https") if self.proxies else "none",
        )

        while True:
            if self.gate is not None:
                self.gate.wait()

            # Throttle across all threads via shared adaptive rate limiter.
            # acquire() returns a generation number; if a tile 429 bumps
            # the generation before we fire, we re-acquire instead of
            # sending a request that will certainly be rejected.
            if self.limiter is not None:
                gen = self.limiter.acquire()

                if self.limiter.is_stale(gen):
                    continue

            try:
                resp = self._cast_vote()
                body = resp.json()

            except requests.RequestException:
                logger.exception("[{}] Request failed", self.label)
                time.sleep(10)
                continue

            except ValueError:
                logger.error("[{}] Invalid JSON in response", self.label)
                time.sleep(10)
                continue

            if resp.status_code == 200:
                remaining = body.get("vote_budget", {}).get("remaining", "?")
                logger.info("[{}] Vote OK ({} remaining)", self.label, remaining)

                if self.limiter is not None:
                    self.limiter.on_success()

                if remaining == 0:
                    self._wait_until_reset(body)

            elif resp.status_code == 429:
                error_msg = body.get("error", "unknown")
                logger.warning("[{}] Rate limited: {}", self.label, error_msg)

                if "vote_budget" in body:
                    self._wait_until_reset(body)
                elif self.limiter is not None:
                    self.limiter.on_tile_limited()
                else:
                    time.sleep(
                        random.uniform(
                            TILE_BACKOFF_MIN_SECONDS, TILE_BACKOFF_MAX_SECONDS
                        )
                    )

            else:
                logger.error(
                    "[{}] Unexpected status {}: {}",
                    self.label,
                    resp.status_code,
                    resp.text,
                )
                time.sleep(10)
