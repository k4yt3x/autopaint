from unittest.mock import patch

from autopaint.ratelimit import (
    ADDITIVE_INCREASE,
    COOLDOWN_SECONDS,
    INITIAL_RATE,
    MAX_RATE,
    MIN_RATE,
    MULTIPLICATIVE_DECREASE,
    AdaptiveRateLimiter,
)


class TestAdaptiveRateLimiterInit:
    def test_defaults(self):
        limiter = AdaptiveRateLimiter()
        assert limiter.rate == INITIAL_RATE

    def test_custom_rate(self):
        limiter = AdaptiveRateLimiter(initial_rate=5.0)
        assert limiter.rate == 5.0


class TestOnSuccess:
    def test_rate_increases(self):
        limiter = AdaptiveRateLimiter(initial_rate=1.0)
        limiter.on_success()
        assert limiter.rate == 1.0 + ADDITIVE_INCREASE

    def test_rate_capped_at_max(self):
        limiter = AdaptiveRateLimiter(initial_rate=10.0, max_rate=10.0)
        limiter.on_success()
        assert limiter.rate == 10.0

    def test_rate_uncapped_when_max_disabled(self):
        limiter = AdaptiveRateLimiter(initial_rate=100.0, max_rate=-1)
        limiter.on_success()
        assert limiter.rate == 100.0 + ADDITIVE_INCREASE


class TestOnTileLimited:
    @patch("autopaint.ratelimit.time.sleep")
    def test_rate_decreases(self, mock_sleep):
        limiter = AdaptiveRateLimiter(initial_rate=4.0)
        limiter.on_tile_limited()

        assert limiter.rate == 4.0 * MULTIPLICATIVE_DECREASE

    @patch("autopaint.ratelimit.time.sleep")
    def test_rate_floored_at_min(self, mock_sleep):
        limiter = AdaptiveRateLimiter(initial_rate=0.5, min_rate=0.5)
        limiter.on_tile_limited()

        assert limiter.rate == 0.5

    @patch("autopaint.ratelimit.time.sleep")
    def test_rate_no_floor_when_min_disabled(self, mock_sleep):
        limiter = AdaptiveRateLimiter(initial_rate=0.01, min_rate=-1)
        limiter.on_tile_limited()

        assert limiter.rate == 0.01 * MULTIPLICATIVE_DECREASE

    @patch("autopaint.ratelimit.time.sleep")
    @patch("autopaint.ratelimit.time.monotonic")
    def test_cooldown_prevents_double_decrease(self, mock_mono, mock_sleep):
        # Simulate two 429s arriving 1 second apart.
        times = [0.0, 0.0, 1.0, 1.0]
        mock_mono.side_effect = times

        limiter = AdaptiveRateLimiter(initial_rate=4.0)
        limiter._last_decrease = 0.0  # reset

        limiter.on_tile_limited()
        rate_after_first = limiter.rate

        limiter.on_tile_limited()
        rate_after_second = limiter.rate

        # Second call within cooldown should be ignored.
        assert rate_after_first == rate_after_second

    @patch("autopaint.ratelimit.time.sleep")
    def test_generation_increments(self, mock_sleep):
        limiter = AdaptiveRateLimiter(initial_rate=4.0)
        gen_before = limiter._generation

        limiter.on_tile_limited()

        assert limiter._generation == gen_before + 1

    @patch("autopaint.ratelimit.time.sleep")
    def test_pause_event_blocks_then_unblocks(self, mock_sleep):
        limiter = AdaptiveRateLimiter(initial_rate=4.0)

        # Before: event should be set (open).
        assert limiter._pause_event.is_set()

        limiter.on_tile_limited()

        # After sleep returns, event should be set again.
        assert limiter._pause_event.is_set()


class TestAcquire:
    @patch("autopaint.ratelimit.time.sleep")
    @patch("autopaint.ratelimit.time.monotonic")
    def test_returns_generation(self, mock_mono, mock_sleep):
        mock_mono.return_value = 100.0
        limiter = AdaptiveRateLimiter(initial_rate=2.0)
        limiter._next_token = 100.0
        limiter._generation = 5

        gen = limiter.acquire()
        assert gen == 5

    @patch("autopaint.ratelimit.time.sleep")
    @patch("autopaint.ratelimit.time.monotonic")
    def test_sleeps_when_backlogged(self, mock_mono, mock_sleep):
        mock_mono.return_value = 100.0
        limiter = AdaptiveRateLimiter(initial_rate=2.0)
        limiter._next_token = 101.0  # 1 second in the future

        limiter.acquire()

        mock_sleep.assert_called_once_with(1.0)


class TestIsStale:
    def test_current_generation_not_stale(self):
        limiter = AdaptiveRateLimiter()
        limiter._generation = 5
        assert limiter.is_stale(5) is False

    def test_older_generation_is_stale(self):
        limiter = AdaptiveRateLimiter()
        limiter._generation = 5
        assert limiter.is_stale(4) is True

    def test_newer_generation_not_stale(self):
        limiter = AdaptiveRateLimiter()
        limiter._generation = 5
        assert limiter.is_stale(6) is False
