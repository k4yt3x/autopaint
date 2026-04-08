# Autopaint

Automated voting bot for the [paintastreet.com](https://paintastreet.com/) ~~CTF~~. Built to manage tile rankings in the Paint a Street competition through multi-session concurrent voting with proxy rotation, adaptive rate limiting, and configurable ranking strategies.

## Architecture

```
autopaint/
  __main__.py   # CLI entry point, argument parsing, thread orchestration
  voter.py      # Per-session voter loop, HTTP requests, cooldown management
  monitor.py    # WebSocket rankings monitor, RankGate (direction control), stall detector
  ratelimit.py  # Adaptive AIMD token-bucket rate limiter
  useragent.py  # User agent fetching, browser-specific header generation
  proxy.py      # Mullvad SOCKS5 proxy fetching
  store.py      # SQLite persistence for session cooldowns and learned rate
tests/
  test_*.py     # pytest suite (109 tests)
```

## How It Works

### Voting

Each session cookie runs in its own thread. On each iteration a voter:

1. **Asks the gate** for a vote direction (`"up"`, `"down"`, or blocks if paused)
2. **Acquires a rate limiter token** (blocks until the adaptive rate allows it)
3. **Sends an HTTP PUT** to the vote endpoint with browser-appropriate headers
4. **Handles the response**: successful votes, per-session budget exhaustion (waits for `reset_at`), and tile-level 429s (triggers rate reduction)

Voters use persistent `requests.Session` objects to reuse TCP/TLS connections across requests, reducing file descriptor usage with many threads.

### Rate Limiting

The **adaptive rate limiter** uses AIMD (Additive-Increase / Multiplicative-Decrease):

- On each successful vote: rate += 0.02 req/s
- On tile-level 429: rate *= 0.7, then all threads are paused for 15s
- A generation counter invalidates stale tokens so threads that acquired before a rate cut skip their request instead of firing into the limit
- A 30s cooldown prevents compounding when multiple threads report 429s simultaneously
- The learned rate is persisted to SQLite and restored on restart

Alternatively, `--rate N` sets a fixed rate with no adaptation, or `--no-throttle` disables the limiter entirely.

### Proxy Rotation

Each voter thread is assigned a random SOCKS5 proxy from Mullvad's relay network at startup. Proxies are fetched from the Mullvad API and filtered by country code. A single custom proxy can also be specified with `--proxy`.

### Browser Fingerprinting

User agents are fetched from a public UA list. Each thread gets a random UA at startup. Headers are tailored to match the browser:

- **Chrome-based UAs**: `sec-ch-ua`, `sec-ch-ua-mobile`, `sec-ch-ua-platform` (derived from the UA string), `DNT: 1`, `Priority: u=1, i`
- **Firefox UAs**: `Sec-GPC: 1`, `TE: trailers`, `Priority: u=0`

The platform header matches the OS in the UA (Windows, macOS, Linux, Android, Chrome OS).

### Ranking Strategies

The **RankGate** monitors tile rankings via a Centrifugo WebSocket and controls vote direction for all threads:

#### Hold Strategy (`--auto-rank`)

Stabilizes the tile at a target rank by targeting the midpoint between the tiles above and below:

- **Below target**: vote up
- **At target, below midpoint**: vote up
- **At target, near midpoint** (within tolerance): pause
- **At target, above midpoint**: vote down
- **Above target**: vote down

The tolerance is `max(vote_buffer, spread * 1.5%)` where spread is the vote difference between the tiles above and below.

#### Top-1 Strategy (`--top1`)

Races to first place then maintains a lead:

- **Not #1**: vote up
- **At #1, lead <= buffer**: vote up
- **At #1, lead > buffer**: pause

#### Passthrough (default)

No rank control. All threads vote up continuously. The WebSocket monitor still runs for stall detection.

### Stall Detection

The server may silently drop votes when a hidden rate limit is exceeded (no 429 returned). The stall detector checks every 2 minutes whether the tile's vote count has increased by at least 5. If not, all threads are paused for 30-60s to let the hidden window expire.

### Persistence

SQLite stores:
- **Session cooldowns**: per-session `reset_at` timestamps so restarts skip the re-discovery period
- **Learned rate**: the adaptive rate limiter's current rate, restored on restart

## Setup

```bash
uv sync
```

Place exported cookies (from [Cookie Quick Manager](https://github.com/ysard/cookie-quick-manager)) into `data/cookies.json`.

## Usage

```bash
# Default: vote up at 6 req/s with stall detection
just run

# Hold 3rd place with midpoint targeting
just run-hold

# Race to #1
just run-top1

# No rate limiting, fire as fast as possible
just run-spam

# Custom tile, proxy, and rate
uv run python -m autopaint -v -t <tile-id> --proxy socks5://127.0.0.1:40000 --rate 5
```

### CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `-c`, `--cookies` | `data/cookies.json` | Path to cookies JSON file |
| `--db` | `data/autopaint.db` | Path to SQLite database |
| `-t`, `--tile-id` | `019d589b-...` | Tile ID to vote on |
| `--no-proxy` | off | Disable proxying |
| `--proxy` | none | Single proxy URL for all threads |
| `--proxy-country` | `us ca` | Mullvad proxy country codes |
| `--auto-rank` | off | Enable hold strategy |
| `--top1` | off | Enable top-1 strategy |
| `--rank-target` | `3` | Target rank for hold strategy |
| `--rank-resume` | `4` | Safety fallback rank |
| `--vote-buffer` | `10` | Tolerance around midpoint / lead buffer |
| `--rate` | adaptive | Fixed rate in req/s |
| `--no-throttle` | off | Disable rate limiter, keep 429 handling |
| `--no-ratelimit` | off | Disable all rate limiting |
| `--direction` | auto | Force `up` or `down` |
| `-v` | off | Verbose logging |

## Testing

```bash
just test
```
