import argparse
import json
import random
import sys
import threading

from loguru import logger

from autopaint.proxy import fetch_proxies
from autopaint.ratelimit import AdaptiveRateLimiter
from autopaint.useragent import fetch_user_agents
from autopaint.voter import Voter

DEFAULT_TILE_ID = "019d589b-0d7b-720e-9a3c-1c8ecbc90a09"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated voter for paintastreet.com",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--cookies",
        default="data/cookies.json",
        help="path to cookies JSON file",
    )
    parser.add_argument(
        "-t",
        "--tile-id",
        default=DEFAULT_TILE_ID,
        help="tile ID to vote on",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="disable SOCKS5 proxy via Mullvad",
    )
    parser.add_argument(
        "--proxy-country",
        nargs="+",
        default=["us", "ca"],
        help="Mullvad proxy country codes",
    )
    parser.add_argument(
        "--auto-rank",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="automatically pause/resume voting based on tile ranking",
    )
    parser.add_argument(
        "--rank-target",
        type=int,
        default=3,
        help="pause voting once tile reaches this rank",
    )
    parser.add_argument(
        "--rank-resume",
        type=int,
        default=5,
        help="resume voting when tile falls below this rank",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable debug logging",
    )
    args = parser.parse_args()

    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if args.verbose else "INFO",
        format="<green>{time:HH:mm:ss}</green> <level>{level:<8}</level> {message}",
    )

    with open(args.cookies) as f:
        cookies = json.load(f)

    sessions = [c["Content raw"] for c in cookies]
    logger.info("Loaded {} sessions from {}", len(sessions), args.cookies)

    user_agents = fetch_user_agents()
    proxies = [] if args.no_proxy else fetch_proxies(args.proxy_country)

    gate = None

    if args.auto_rank:
        from autopaint.monitor import RankGate, start_monitor

        gate = RankGate(args.tile_id, args.rank_target, args.rank_resume)
        start_monitor(gate, random.choice(user_agents))

    limiter = AdaptiveRateLimiter()
    threads: list[threading.Thread] = []

    for index, session_cookie in enumerate(sessions, start=1):
        user_agent = random.choice(user_agents)
        proxy = random.choice(proxies) if proxies else None
        voter = Voter(
            index,
            session_cookie,
            user_agent,
            args.tile_id,
            proxy=proxy,
            gate=gate,
            limiter=limiter,
        )
        thread = threading.Thread(target=voter.run, daemon=True)
        thread.start()
        threads.append(thread)

    logger.info("Launched {} voter threads", len(threads))

    try:
        for thread in threads:
            thread.join()

    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down")
        sys.exit(0)


if __name__ == "__main__":
    main()
