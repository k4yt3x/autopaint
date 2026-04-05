import threading
import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from autopaint.store import Store

# AIMD parameters
INITIAL_RATE = 6.0  # requests per second
MIN_RATE = 0.2  # floor: 1 request per 5s
MAX_RATE = 20.0  # ceiling
ADDITIVE_INCREASE = 0.02  # req/s added per success
MULTIPLICATIVE_DECREASE = 0.7  # reduce to 70% on a 429 burst
COOLDOWN_SECONDS = 30.0  # ignore duplicate 429s within this window
PAUSE_SECONDS = 15.0  # block all threads after a tile 429
LOG_INTERVAL_SECONDS = 30  # how often to print the learned rate


class AdaptiveRateLimiter:
    """Adaptive token-bucket rate limiter shared across all voter threads.

    Uses AIMD (additive-increase / multiplicative-decrease) to converge on
    the server's actual tile-level rate limit.

    When a tile 429 is reported:
    1. The rate is reduced (multiplicative decrease).
    2. A global pause blocks *all* threads for :data:`PAUSE_SECONDS` so the
       server's rate-limit window can expire before any retries.
    3. The generation counter is bumped so threads still sleeping on stale
       tokens skip directly to re-acquiring.

    The current learned rate is logged periodically so it can be observed
    and later set as a default.
    """

    def __init__(
        self,
        initial_rate: float = INITIAL_RATE,
        min_rate: float = MIN_RATE,
        max_rate: float = MAX_RATE,
        store: "Store | None" = None,
    ) -> None:
        self._min_rate = min_rate
        self._max_rate = max_rate
        self._store = store

        # Try to restore the learned rate from a previous run.
        restored = None
        if store is not None:
            raw = store.get_value("learned_rate")
            if raw is not None:
                try:
                    restored = max(min_rate, min(float(raw), max_rate))
                except ValueError:
                    pass

        if restored is not None:
            self._rate = restored
            logger.info("Restored learned rate: {:.2f} req/s", restored)
        else:
            self._rate = initial_rate

        self._lock = threading.Lock()
        self._next_token: float = time.monotonic()
        self._last_log: float = time.monotonic()
        self._last_decrease: float = 0.0
        self._generation: int = 0

        # Pause gate: cleared during a tile-limit pause, set when open.
        self._pause_event = threading.Event()
        self._pause_event.set()

    @property
    def rate(self) -> float:
        with self._lock:
            return self._rate

    def acquire(self) -> int:
        """Block until the pause lifts and the next token is available.

        Returns the current generation number so the caller can detect
        stale tokens via :meth:`is_stale`.
        """
        # Wait for any active pause to lift before queuing for a token.
        self._pause_event.wait()

        with self._lock:
            now = time.monotonic()
            wait = self._next_token - now

            if wait > 0:
                self._next_token += 1.0 / self._rate
            else:
                self._next_token = now + 1.0 / self._rate

            gen = self._generation

        if wait > 0:
            time.sleep(wait)

        return gen

    def is_stale(self, generation: int) -> bool:
        """Return True if *generation* is older than current (rate was cut)."""
        with self._lock:
            return generation < self._generation

    def on_success(self) -> None:
        """Called after a successful vote (HTTP 200). Gently increases rate."""
        with self._lock:
            self._rate = min(self._rate + ADDITIVE_INCREASE, self._max_rate)
            self._maybe_log()

    def on_tile_limited(self) -> None:
        """Called after a tile-level 429.

        Reduces the rate, bumps the generation, and pauses all threads for
        :data:`PAUSE_SECONDS` so the server's window can expire.

        Duplicate 429s arriving within :data:`COOLDOWN_SECONDS` of the last
        reduction are ignored to prevent compounding.
        """
        with self._lock:
            now = time.monotonic()

            if now - self._last_decrease < COOLDOWN_SECONDS:
                return

            self._last_decrease = now
            self._rate = max(self._rate * MULTIPLICATIVE_DECREASE, self._min_rate)
            self._generation += 1
            self._next_token = now + PAUSE_SECONDS

            logger.warning(
                "Tile rate limit hit, reducing to {:.2f} req/s, pausing {:.0f}s",
                self._rate,
                PAUSE_SECONDS,
            )
            self._last_log = now

        # Block all threads (including those about to call acquire).
        self._pause_event.clear()
        time.sleep(PAUSE_SECONDS)
        self._pause_event.set()

    def _maybe_log(self) -> None:
        """Log and persist the current rate periodically (caller must hold _lock)."""
        now = time.monotonic()

        if now - self._last_log >= LOG_INTERVAL_SECONDS:
            logger.info("Adaptive rate: {:.2f} req/s", self._rate)
            self._last_log = now

            if self._store is not None:
                self._store.set_value("learned_rate", f"{self._rate:.4f}")
