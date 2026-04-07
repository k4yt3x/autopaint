import asyncio
import json
import random
import threading
import time

import websockets
import websockets.exceptions
from loguru import logger

WS_URL = "wss://please.paintastreet.com/connection/websocket"

RECONNECT_DELAY_SECONDS = 5
PING_INTERVAL_SECONDS = 25

# Stall detection: if our vote count gains fewer than this many votes
# over the check interval, we're probably being silently rate-limited.
STALL_CHECK_INTERVAL = 120  # seconds between checks
STALL_MIN_EXPECTED_GAIN = 5  # fewer than this = stalled
STALL_PAUSE_MIN = 30  # seconds
STALL_PAUSE_MAX = 60  # seconds


class RankGate:
    """Thread-safe gate that stabilizes a tile at a target rank.

    Voters call :meth:`get_direction` which blocks until the gate decides
    whether to vote ``"up"`` (climb/maintain), ``"down"`` (drop back), or
    pause (``None`` internally — the caller blocks).

    Strategy:
    - rank > rank_target → vote **up**
    - rank = rank_target and votes < (2nd-place votes - buffer) → vote **up**
    - rank = rank_target and votes >= (2nd-place votes - buffer) → **pause**
    - rank < rank_target → vote **down**
    - rank > rank_resume (safety fallback) → vote **up**
    """

    def __init__(
        self,
        tile_id: str,
        rank_target: int = 3,
        rank_resume: int = 5,
        vote_buffer: int = 50,
        top1: bool = False,
        passthrough: bool = False,
    ) -> None:
        self.tile_id = tile_id
        self.rank_target = rank_target
        self.rank_resume = rank_resume
        self.vote_buffer = vote_buffer
        self.top1 = top1
        self.passthrough = passthrough

        self._rankings: dict[str, int] = {}
        self._position: int | None = None
        self._direction: str | None = None
        self._stall_paused: bool = False
        self._lock = threading.Lock()
        self._event = threading.Event()

        # Start with "up" so voters proceed before the first WS update.
        self._direction = "up"
        self._event.set()

    @property
    def position(self) -> int | None:
        with self._lock:
            return self._position

    def get_direction(self) -> str:
        """Block until a vote direction is available, then return it."""
        self._event.wait()

        with self._lock:
            # Direction could have been cleared between wait and lock.
            if self._direction is not None:
                return self._direction

        # Rare race — re-wait.
        return self.get_direction()

    def _recompute_position(self) -> int | None:
        """Derive the 1-based rank of the tracked tile from stored vote counts."""
        our_count = self._rankings.get(self.tile_id)

        if our_count is None:
            return None

        rank = 1
        for tid, count in self._rankings.items():
            if tid != self.tile_id and count > our_count:
                rank += 1

        return rank

    def _get_nth_place_votes(self, n: int) -> int | None:
        """Return the vote count of the tile at rank *n*, or None."""
        sorted_counts = sorted(self._rankings.values(), reverse=True)

        if n <= 0 or n > len(sorted_counts):
            return None

        return sorted_counts[n - 1]

    def get_our_votes(self) -> int | None:
        """Return the current vote count of the tracked tile."""
        with self._lock:
            return self._rankings.get(self.tile_id)

    def set_stall_paused(self, paused: bool) -> None:
        """Temporarily pause/resume voting due to stall detection."""
        with self._lock:
            self._stall_paused = paused

            if paused:
                self._direction = None
            else:
                self._direction = self._compute_direction()

        if self._direction is not None:
            self._event.set()
        else:
            self._event.clear()

    def _compute_direction(self) -> str | None:
        """Decide vote direction based on current rank and vote gap."""
        if self._stall_paused:
            return None

        if self.passthrough:
            return "up"

        if self.top1:
            return self._compute_direction_top1()
        return self._compute_direction_hold()

    def _compute_direction_top1(self) -> str | None:
        """Top-1 strategy: race to #1, then pause when lead exceeds buffer."""
        pos = self._position

        if pos is None:
            return "up"

        # Not #1 yet — keep voting up.
        if pos > 1:
            return "up"

        # At #1 — check lead over 2nd place.
        second_votes = self._get_nth_place_votes(2)
        our_votes = self._rankings.get(self.tile_id)

        if second_votes is None or our_votes is None:
            return "up"

        if our_votes > second_votes + self.vote_buffer:
            return None

        return "up"

    def _compute_direction_hold(self) -> str | None:
        """Hold strategy: stabilize at rank_target by targeting the midpoint
        between the tiles above and below."""
        pos = self._position

        if pos is None:
            return "up"

        # Safety fallback: if we've fallen far, always vote up.
        if pos > self.rank_resume:
            return "up"

        # Below target (rank number higher = worse position): vote up.
        if pos > self.rank_target:
            return "up"

        # Above target (rank 1 or 2 when target is 3): vote down.
        if pos < self.rank_target:
            return "down"

        # At target rank — aim for midpoint between neighbors.
        above_votes = self._get_nth_place_votes(self.rank_target - 1)
        below_votes = self._get_nth_place_votes(self.rank_target + 1)
        our_votes = self._rankings.get(self.tile_id)

        if our_votes is None:
            return "up"

        # Fall back to buffer-from-above if neighbors are unavailable.
        if above_votes is None or below_votes is None:
            if above_votes is not None and our_votes < above_votes - self.vote_buffer:
                return "up"
            return None

        midpoint = (above_votes + below_votes) / 2
        spread = above_votes - below_votes
        tolerance = max(self.vote_buffer, spread * 0.015)

        if our_votes < midpoint - tolerance:
            return "up"

        if our_votes > midpoint + tolerance:
            return "down"

        return None

    def update_rankings(self, tiles: dict[str, int]) -> None:
        """Merge a batch of tile vote counts and re-evaluate the gate."""
        with self._lock:
            self._rankings.update(tiles)
            self._position = self._recompute_position()

            old_dir = self._direction
            self._direction = self._compute_direction()

        if self._position is None:
            return

        # Log direction changes.
        if self._direction != old_dir:
            if self._direction is None:
                our = self._rankings.get(self.tile_id, 0)
                above = self._get_nth_place_votes(self.rank_target - 1)
                below = self._get_nth_place_votes(self.rank_target + 1)

                if above is not None and below is not None:
                    mid = (above + below) / 2
                    spread = above - below
                    tol = max(self.vote_buffer, spread * 0.015)
                    logger.info(
                        "Rank #{}: pausing (votes={}, midpoint={:.0f}, ±{:.0f})",
                        self._position,
                        our,
                        mid,
                        tol,
                    )
                else:
                    logger.info(
                        "Rank #{}: pausing (votes={}, #{}={})",
                        self._position,
                        our,
                        self.rank_target - 1,
                        above or "?",
                    )
            else:
                logger.info(
                    "Rank #{}: voting {} (was {})",
                    self._position,
                    self._direction,
                    old_dir or "paused",
                )

        # Update the event to unblock/block waiting threads.
        if self._direction is not None:
            self._event.set()
        else:
            self._event.clear()


# ---------------------------------------------------------------------------
# Websocket monitor
# ---------------------------------------------------------------------------


async def _monitor_loop(gate: RankGate, user_agent: str) -> None:
    """Connect to the rankings websocket and keep the gate updated."""
    headers = {
        "Origin": "https://paintastreet.com",
        "User-Agent": user_agent,
    }

    while True:
        try:
            async with websockets.connect(
                WS_URL, additional_headers=headers
            ) as ws:
                # Centrifugo connect handshake
                await ws.send(json.dumps({"id": 1, "connect": {}}))
                connect_raw = str(
                    await asyncio.wait_for(ws.recv(), timeout=10)
                )
                connect_resp = json.loads(connect_raw.split("\n")[0])
                ping_interval = connect_resp.get("connect", {}).get(
                    "ping", PING_INTERVAL_SECONDS
                )
                logger.debug("WS connected, ping interval={}s", ping_interval)

                # Subscribe to rankings channel
                await ws.send(
                    json.dumps({"id": 2, "subscribe": {"channel": "rankings"}})
                )

                while True:
                    raw = str(
                        await asyncio.wait_for(
                            ws.recv(), timeout=ping_interval + 10
                        )
                    )

                    # Centrifugo may batch multiple JSON objects in one
                    # message, separated by newlines.
                    for line in raw.split("\n"):
                        line = line.strip()

                        if not line:
                            continue

                        data = json.loads(line)

                        # Handle server ping (empty object)
                        if data == {}:
                            await ws.send(json.dumps({}))
                            continue

                        # Initial subscribe response
                        if "subscribe" in data:
                            _process_tiles(
                                gate, data["subscribe"].get("data", {})
                            )
                            continue

                        # Publication push
                        push = data.get("push", {})
                        pub_data = push.get("pub", {}).get("data", {})

                        if pub_data.get("type") == "rankings_patch":
                            _process_tiles(gate, pub_data, patch=True)
                        elif "tiles" in pub_data:
                            _process_tiles(gate, pub_data)

        except (
            websockets.exceptions.ConnectionClosed,
            asyncio.TimeoutError,
            OSError,
        ) as exc:
            logger.warning(
                "WS disconnected ({}), reconnecting in {}s",
                exc,
                RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)

        except Exception:
            logger.exception(
                "WS unexpected error, reconnecting in {}s", RECONNECT_DELAY_SECONDS
            )
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


def _process_tiles(
    gate: RankGate,
    data: dict,
    *,
    patch: bool = False,
) -> None:
    """Extract tile vote counts from a snapshot or patch and feed the gate."""
    source = data.get("upserts" if patch else "tiles", [])
    counts: dict[str, int] = {}

    for tile in source:
        tid = tile.get("id")
        raw = tile.get("vote_count")

        if tid is None or raw is None:
            continue

        count = int(raw)
        counts[tid] = count

    if not counts:
        return

    old_pos = gate.position
    gate.update_rankings(counts)
    new_pos = gate.position

    if new_pos is None:
        return

    # Full snapshot: always log. Patch: only log when our position changed.
    if not patch:
        logger.info(
            "Tile {} position: #{} (votes: {})",
            gate.tile_id[:8],
            new_pos,
            counts.get(gate.tile_id, "?"),
        )
    elif new_pos != old_pos:
        logger.debug(
            "Tile {} position changed: #{} -> #{}",
            gate.tile_id[:8],
            old_pos,
            new_pos,
        )


def _stall_detector_loop(gate: RankGate) -> None:
    """Periodically check if our vote count is stalling despite active voting.

    If the tile's vote count barely increases over :data:`STALL_CHECK_INTERVAL`,
    the server is likely silently dropping votes. Temporarily pause to let the
    hidden rate limit window expire.
    """
    prev_votes: int | None = None

    while True:
        time.sleep(STALL_CHECK_INTERVAL)

        current_votes = gate.get_our_votes()

        if current_votes is None or prev_votes is None:
            prev_votes = current_votes
            continue

        # Only check when the gate is actively voting (not paused by strategy).
        if not gate._event.is_set():
            prev_votes = current_votes
            continue

        gain = current_votes - prev_votes
        prev_votes = current_votes

        if gain >= STALL_MIN_EXPECTED_GAIN:
            continue

        # Stall detected — pause briefly.
        pause = random.uniform(STALL_PAUSE_MIN, STALL_PAUSE_MAX)
        logger.warning(
            "Stall detected: only +{} votes in {}s, pausing {:.0f}s",
            gain,
            STALL_CHECK_INTERVAL,
            pause,
        )

        gate.set_stall_paused(True)
        time.sleep(pause)
        gate.set_stall_paused(False)

        logger.info("Stall pause ended, resuming voting")

        # Reset baseline after pause.
        prev_votes = gate.get_our_votes()


def start_ws_monitor(gate: RankGate, user_agent: str) -> threading.Thread:
    """Launch only the websocket rankings monitor."""

    def _run() -> None:
        asyncio.run(_monitor_loop(gate, user_agent))

    thread = threading.Thread(target=_run, daemon=True, name="vote-monitor")
    thread.start()

    logger.info("WS rankings monitor started (tile={})", gate.tile_id[:8])
    return thread


def start_stall_detector(gate: RankGate) -> threading.Thread:
    """Launch only the stall detector."""
    thread = threading.Thread(
        target=_stall_detector_loop,
        args=(gate,),
        daemon=True,
        name="stall-detector",
    )
    thread.start()

    logger.info("Stall detector started (check={}s, min_gain={})",
                STALL_CHECK_INTERVAL, STALL_MIN_EXPECTED_GAIN)
    return thread


def start_monitor(gate: RankGate, user_agent: str) -> threading.Thread:
    """Launch the full monitor suite: WS rankings + stall detector."""
    thread = start_ws_monitor(gate, user_agent)
    start_stall_detector(gate)

    mode = "top1" if gate.top1 else f"hold #{gate.rank_target}"
    logger.info(
        "Vote monitor started (tile={}, mode={}, buffer={})",
        gate.tile_id[:8],
        mode,
        gate.vote_buffer,
    )

    return thread
