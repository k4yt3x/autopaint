from __future__ import annotations

import asyncio
import json
import threading

import websockets
from loguru import logger

WS_URL = "wss://please.paintastreet.com/connection/websocket"

RECONNECT_DELAY_SECONDS = 5
PING_INTERVAL_SECONDS = 25


class RankGate:
    """Thread-safe gate that pauses voting based on tile ranking position.

    Voting is paused once the tile reaches *rank_target* (e.g. top 5) and
    resumed when it falls below *rank_resume* (e.g. drops past 8th place).
    The hysteresis avoids rapid toggling near the boundary.
    """

    def __init__(
        self,
        tile_id: str,
        rank_target: int = 5,
        rank_resume: int = 8,
    ) -> None:
        self.tile_id = tile_id
        self.rank_target = rank_target
        self.rank_resume = rank_resume

        self._rankings: dict[str, int] = {}
        self._position: int | None = None
        self._lock = threading.Lock()
        self._event = threading.Event()

        # Start open so voters can proceed before the first WS update arrives.
        self._event.set()

    @property
    def position(self) -> int | None:
        with self._lock:
            return self._position

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

    def update_rankings(self, tiles: dict[str, int]) -> None:
        """Merge a batch of tile vote counts and re-evaluate the gate."""
        with self._lock:
            self._rankings.update(tiles)
            new_pos = self._recompute_position()
            old_pos = self._position
            self._position = new_pos

        if new_pos is None:
            return

        if new_pos <= self.rank_target:
            if old_pos is None or old_pos > self.rank_target:
                logger.warning(
                    "Tile reached rank {} (<= target {}), pausing voting",
                    new_pos,
                    self.rank_target,
                )
            self._event.clear()

        elif new_pos > self.rank_resume:
            if old_pos is not None and old_pos <= self.rank_resume:
                logger.info(
                    "Tile fell to rank {} (> resume {}), resuming voting",
                    new_pos,
                    self.rank_resume,
                )
            self._event.set()

    def wait(self) -> None:
        """Block until voting is allowed."""
        self._event.wait()


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
                connect_raw = await asyncio.wait_for(ws.recv(), timeout=10)
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
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=ping_interval + 10
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

        except Exception:
            logger.exception(
                "WS connection lost, reconnecting in {}s", RECONNECT_DELAY_SECONDS
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


def start_monitor(gate: RankGate, user_agent: str) -> threading.Thread:
    """Launch the vote monitor in a background daemon thread."""

    def _run() -> None:
        asyncio.run(_monitor_loop(gate, user_agent))

    thread = threading.Thread(target=_run, daemon=True, name="vote-monitor")
    thread.start()

    logger.info(
        "Vote monitor started (tile={}, target=top {}, resume=below {})",
        gate.tile_id[:8],
        gate.rank_target,
        gate.rank_resume,
    )

    return thread
