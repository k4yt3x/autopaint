from __future__ import annotations

import random
import time
from datetime import datetime, timezone

import requests
from loguru import logger

VOTE_URL_TEMPLATE = "https://please.paintastreet.com/tiles/{tile_id}/vote"
UA_LIST_URL = (
    "https://raw.githubusercontent.com/MichaelJorky/"
    "top-user-agents-latest/refs/heads/main/data/browsers/browsers_1.txt"
)

DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Referer": "https://paintastreet.com/",
    "content-type": "application/json",
    "Origin": "https://paintastreet.com",
    "Sec-GPC": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Priority": "u=0",
    "TE": "trailers",
}

MULLVAD_RELAYS_URL = "https://api.mullvad.net/public/relays/wireguard/v2"

FALLBACK_WAIT_SECONDS = 600
TILE_BACKOFF_MIN_SECONDS = 10
TILE_BACKOFF_MAX_SECONDS = 60


def fetch_user_agents() -> list[str]:
    """Fetch the latest user agent list from GitHub."""
    resp = requests.get(UA_LIST_URL, timeout=30)
    resp.raise_for_status()
    agents = [line.strip() for line in resp.text.splitlines() if line.strip()]
    logger.info("Fetched {} user agents", len(agents))
    return agents


def fetch_proxies(country: str) -> list[str]:
    """Fetch SOCKS5 proxy addresses from Mullvad for a given country code."""
    resp = requests.get(MULLVAD_RELAYS_URL, timeout=30)
    resp.raise_for_status()
    proxies: list[str] = []
    for relay in resp.json()["wireguard"]["relays"]:
        if relay["location"].startswith(f"{country}-") and relay["active"]:
            host = relay["hostname"].replace("wg-", "wg-socks5-")
            proxies.append(f"socks5://{host}.relays.mullvad.net:1080")
    logger.info("Fetched {} Mullvad proxies for country={}", len(proxies), country)
    return proxies


class Voter:
    def __init__(
        self,
        index: int,
        session_cookie: str,
        user_agent: str,
        tile_id: str,
        proxy: str | None = None,
    ) -> None:
        self.session_cookie = session_cookie
        self.tile_id = tile_id
        self.url = VOTE_URL_TEMPLATE.format(tile_id=tile_id)
        self.headers = {
            **DEFAULT_HEADERS,
            "User-Agent": user_agent,
            "Cookie": f"session={session_cookie}",
        }
        self.proxies = {"https": proxy} if proxy else None
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
            except (ValueError, TypeError):
                pass

        window = budget.get("window_seconds")
        if window:
            return int(window) + 1

        return FALLBACK_WAIT_SECONDS

    def _wait_until_reset(self, body: dict) -> None:
        """Sleep until the vote budget resets based on the response body."""
        wait = self._get_wait_seconds(body)
        logger.info("[{}] Waiting {:.0f}s until reset", self.label, wait)
        time.sleep(wait)

    def run(self) -> None:
        """Vote in a loop, respecting rate limits. Runs forever."""
        logger.info("[{}] Starting voter", self.label)
        logger.debug("[{}] UA: {}", self.label, self.headers["User-Agent"])
        logger.debug("[{}] Proxy: {}", self.label, self.proxies.get("https") if self.proxies else "none")
        while True:
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
                if remaining == 0:
                    self._wait_until_reset(body)
            elif resp.status_code == 429:
                error_msg = body.get("error", "unknown")
                logger.warning("[{}] Rate limited: {}", self.label, error_msg)
                if "vote_budget" in body:
                    self._wait_until_reset(body)
                else:
                    # Tile-level rate limit (no budget info).
                    # Back off briefly with jitter before retrying.
                    wait = random.uniform(TILE_BACKOFF_MIN_SECONDS, TILE_BACKOFF_MAX_SECONDS)
                    logger.info(
                        "[{}] Tile rate limit, retrying in {:.0f}s", self.label, wait
                    )
                    time.sleep(wait)
            else:
                logger.error(
                    "[{}] Unexpected status {}: {}",
                    self.label,
                    resp.status_code,
                    resp.text,
                )
                time.sleep(10)
