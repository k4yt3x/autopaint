import argparse
import json
import random
import resource
import sys
import threading

from loguru import logger

from autopaint.proxy import fetch_proxies
from autopaint.ratelimit import AdaptiveRateLimiter
from autopaint.store import Store
from autopaint.useragent import fetch_user_agents
from autopaint.voter import ActiveVoterTracker, Voter

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
        "--proxy",
        help="use a single proxy for all threads (e.g. socks5://127.0.0.1:40000)",
    )
    parser.add_argument(
        "--proxy-country",
        nargs="+",
        default=["us", "ca", "mx"],
        help="Mullvad proxy country codes",
    )
    parser.add_argument(
        "--auto-rank",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="hold tile at rank-target, voting down if above",
    )
    parser.add_argument(
        "--top1",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="race to #1 then pause when lead exceeds vote-buffer",
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
        default=4,
        help="resume voting when tile falls below this rank",
    )
    parser.add_argument(
        "--vote-buffer",
        type=int,
        default=10,
        help="tolerance (±) around the midpoint between neighbors",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=None,
        help="fixed rate limit in req/s (disables adaptive AIMD)",
    )
    parser.add_argument(
        "--no-throttle",
        action="store_true",
        help="disable adaptive rate limiter but still respect 429s and cooldowns",
    )
    parser.add_argument(
        "--no-ratelimit",
        action="store_true",
        help="disable all rate limiting and vote as fast as possible",
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

    # Raise the file descriptor limit to avoid "Too many open files" with
    # many threads each holding SOCKS + TLS connections.
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)

    if soft < hard:
        resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
        logger.debug("Raised fd limit from {} to {}", soft, hard)

    with open(args.cookies) as f:
        cookies = json.load(f)

    sessions = [c["Content raw"] for c in cookies]
    logger.info("Loaded {} sessions from {}", len(sessions), args.cookies)

    user_agents = fetch_user_agents()

    if args.proxy:
        proxies = [args.proxy]
    elif args.no_proxy:
        proxies = []
    else:
        proxies = fetch_proxies(args.proxy_country)

    from autopaint.monitor import (
        RankGate,
        start_monitor,
        start_stall_detector,
        start_ws_monitor,
    )

    monitor_ua = random.choice(user_agents)

    if args.auto_rank or args.top1:
        gate = RankGate(
            args.tile_id,
            args.rank_target,
            args.rank_resume,
            args.vote_buffer,
            top1=args.top1,
        )
        start_monitor(gate, monitor_ua)
    else:
        # No rank strategy, but still monitor for stall detection.
        gate = RankGate(args.tile_id)
        start_ws_monitor(gate, monitor_ua)
        start_stall_detector(gate)

    store = Store()

    if args.no_ratelimit or args.no_throttle:
        limiter = None
    elif args.rate is not None:
        limiter = AdaptiveRateLimiter(
            initial_rate=args.rate,
            min_rate=args.rate,
            max_rate=args.rate,
        )
    else:
        limiter = AdaptiveRateLimiter(store=store)

    tracker = ActiveVoterTracker(len(sessions))
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
            tracker=tracker,
            store=store,
            no_ratelimit=args.no_ratelimit,
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
        store.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
