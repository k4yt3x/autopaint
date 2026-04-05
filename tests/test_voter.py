import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from autopaint.voter import ActiveVoterTracker, Voter


# ---------------------------------------------------------------------------
# Voter — construction
# ---------------------------------------------------------------------------


class TestVoterInit:
    def test_headers_include_ua_and_cookie(self):
        voter = Voter(1, "abc123", "TestUA/1.0", "tile-001")

        assert voter.headers["User-Agent"] == "TestUA/1.0"
        assert voter.headers["Cookie"] == "session=abc123"

    def test_label_format(self):
        voter = Voter(3, "abcdefgh12345678", "UA", "tile-001")
        assert voter.label == "#03 abcdefgh"

    def test_proxy_none(self):
        voter = Voter(1, "abc", "UA", "tile-001")
        assert voter.proxies is None

    def test_proxy_set(self):
        voter = Voter(1, "abc", "UA", "tile-001", proxy="socks5://proxy:1080")
        assert voter.proxies == {"https": "socks5://proxy:1080"}


# ---------------------------------------------------------------------------
# Voter — _cast_vote direction
# ---------------------------------------------------------------------------


class TestCastVote:
    @patch("autopaint.voter.requests.put")
    def test_default_direction_up(self, mock_put):
        mock_resp = MagicMock()
        mock_put.return_value = mock_resp

        voter = Voter(1, "abc", "UA", "tile-001")
        voter._cast_vote()

        call_kwargs = mock_put.call_args
        assert call_kwargs.kwargs["json"] == {"direction": "up"}

    @patch("autopaint.voter.requests.put")
    def test_custom_direction_down(self, mock_put):
        mock_resp = MagicMock()
        mock_put.return_value = mock_resp

        voter = Voter(1, "abc", "UA", "tile-001")
        voter._cast_vote("down")

        call_kwargs = mock_put.call_args
        assert call_kwargs.kwargs["json"] == {"direction": "down"}

    @patch("autopaint.voter.requests.put")
    def test_url_uses_tile_id(self, mock_put):
        mock_resp = MagicMock()
        mock_put.return_value = mock_resp

        voter = Voter(1, "abc", "UA", "my-tile-id")
        voter._cast_vote()

        call_args = mock_put.call_args
        assert "my-tile-id" in call_args.args[0]


# ---------------------------------------------------------------------------
# Voter — _get_wait_seconds
# ---------------------------------------------------------------------------


class TestGetWaitSeconds:
    def test_uses_reset_at(self):
        voter = Voter(1, "abc", "UA", "tile-001")
        future = datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()
        body = {"vote_budget": {"reset_at": future}}

        wait = voter._get_wait_seconds(body)
        assert wait > 0

    def test_falls_back_to_window_seconds(self):
        voter = Voter(1, "abc", "UA", "tile-001")
        body = {"vote_budget": {"window_seconds": 300}}

        wait = voter._get_wait_seconds(body)
        assert wait == 301

    def test_falls_back_to_default(self):
        voter = Voter(1, "abc", "UA", "tile-001")
        body = {"vote_budget": {}}

        wait = voter._get_wait_seconds(body)
        assert wait == 600  # FALLBACK_WAIT_SECONDS

    def test_invalid_reset_at_falls_back(self):
        voter = Voter(1, "abc", "UA", "tile-001")
        body = {"vote_budget": {"reset_at": "not-a-date"}}

        wait = voter._get_wait_seconds(body)
        assert wait == 600

    def test_past_reset_at_falls_back_to_window(self):
        voter = Voter(1, "abc", "UA", "tile-001")
        body = {
            "vote_budget": {
                "reset_at": "2020-01-01T00:00:00Z",
                "window_seconds": 120,
            }
        }

        wait = voter._get_wait_seconds(body)
        assert wait == 121


# ---------------------------------------------------------------------------
# Voter — run loop (one iteration)
# ---------------------------------------------------------------------------


class TestVoterRun:
    @patch("autopaint.voter.time.sleep")
    @patch("autopaint.voter.requests.put")
    def test_successful_vote_calls_limiter(self, mock_put, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "vote_budget": {"remaining": 5}
        }
        mock_put.return_value = mock_resp

        limiter = MagicMock()
        limiter.acquire.return_value = 0
        limiter.is_stale.return_value = False

        voter = Voter(1, "abc", "UA", "tile-001", limiter=limiter)

        # Run one iteration then stop.
        call_count = 0
        original_cast = voter._cast_vote

        def cast_once(direction="up"):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise KeyboardInterrupt
            return original_cast(direction)

        voter._cast_vote = cast_once

        try:
            voter.run()
        except KeyboardInterrupt:
            pass

        limiter.on_success.assert_called_once()

    @patch("autopaint.voter.time.sleep")
    @patch("autopaint.voter.requests.put")
    def test_tile_429_calls_limiter_on_tile_limited(self, mock_put, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.json.return_value = {
            "error": "tile vote rate limit exceeded"
        }
        mock_put.return_value = mock_resp

        limiter = MagicMock()
        limiter.acquire.return_value = 0
        limiter.is_stale.return_value = False

        voter = Voter(1, "abc", "UA", "tile-001", limiter=limiter)

        call_count = 0
        original_cast = voter._cast_vote

        def cast_once(direction="up"):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise KeyboardInterrupt
            return original_cast(direction)

        voter._cast_vote = cast_once

        try:
            voter.run()
        except KeyboardInterrupt:
            pass

        limiter.on_tile_limited.assert_called_once()

    @patch("autopaint.voter.time.sleep")
    @patch("autopaint.voter.requests.put")
    def test_gate_direction_passed_to_cast_vote(self, mock_put, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"vote_budget": {"remaining": 5}}
        mock_put.return_value = mock_resp

        gate = MagicMock()
        gate.get_direction.return_value = "down"

        limiter = MagicMock()
        limiter.acquire.return_value = 0
        limiter.is_stale.return_value = False

        voter = Voter(1, "abc", "UA", "tile-001", gate=gate, limiter=limiter)

        call_count = 0
        original_cast = voter._cast_vote

        def cast_once(direction="up"):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise KeyboardInterrupt
            return original_cast(direction)

        voter._cast_vote = cast_once

        try:
            voter.run()
        except KeyboardInterrupt:
            pass

        # Verify the PUT was called with "down".
        call_kwargs = mock_put.call_args
        assert call_kwargs.kwargs["json"] == {"direction": "down"}


# ---------------------------------------------------------------------------
# ActiveVoterTracker
# ---------------------------------------------------------------------------


class TestActiveVoterTracker:
    def test_initial_state(self):
        tracker = ActiveVoterTracker(10)
        assert tracker._active == 10

    def test_enter_cooldown_decrements(self):
        tracker = ActiveVoterTracker(3)
        tracker.enter_cooldown()
        assert tracker._active == 2

    def test_leave_cooldown_increments(self):
        tracker = ActiveVoterTracker(3)
        tracker.enter_cooldown()
        tracker.leave_cooldown()
        assert tracker._active == 3

    def test_warns_when_all_on_cooldown(self):
        tracker = ActiveVoterTracker(2)
        tracker.enter_cooldown()

        with patch("autopaint.voter.logger") as mock_logger:
            tracker.enter_cooldown()
            mock_logger.warning.assert_called_once()

    def test_no_double_warning(self):
        tracker = ActiveVoterTracker(1)

        with patch("autopaint.voter.logger") as mock_logger:
            tracker.enter_cooldown()
            # Warning fires once.
            assert mock_logger.warning.call_count == 1

    def test_warning_resets_after_leave(self):
        tracker = ActiveVoterTracker(1)
        tracker.enter_cooldown()
        tracker.leave_cooldown()

        with patch("autopaint.voter.logger") as mock_logger:
            tracker.enter_cooldown()
            mock_logger.warning.assert_called_once()
