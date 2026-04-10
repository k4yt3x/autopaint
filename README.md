# Autopaint

Automated voting bot for the [paintastreet.com](https://paintastreet.com/) ~~CTF~~. Built to manage tile rankings in the Paint a Street competition through multi-session concurrent voting with proxy rotation, adaptive rate limiting, and configurable ranking strategies.

<img width="2504" height="1219" alt="image" src="https://github.com/user-attachments/assets/1edddf57-f781-4c97-925f-3c0a43e82bb3" />

## How It Worked

1. **No turnstile required for voting**: The vote API endpoint only validates the session cookie, not a Cloudflare Turnstile token. Each session gets 10 votes per 10-minute window, so more sessions means more votes.
2. **Session farming**: One Turnstile solve produces one session cookie. Using Firefox temporary containers and a userscript to auto-open tabs, sessions could be farmed passively. With Cloudflare WARP and a normal browser fingerprint (canvas, WebGL, etc.), the Turnstile challenge auto-solves without interaction. Around 1,200 sessions were collected before understanding the rate limits, though only ~360 are needed.
3. **One thread per session**: Each session cookie runs in its own thread with a random user agent and a random Mullvad SOCKS5 proxy to distribute traffic and avoid bans.
4. **Per-tile rate limit (~6-7 req/s)**: The server enforced a tile-level rate limit that returned 429 errors when exceeded. An adaptive AIMD rate limiter (similar to TCP congestion control) was built to discover and stay just below this limit. This means infinite sessions and IPs don't give infinite voting speed — throughput is capped by the tile limit.
5. **Silent rate limiting**: The explicit 429 rate limiter was later removed and replaced with a silent one that accepts requests but drops the votes without counting them. The adaptive limiter's last learned rate (~6 req/s) was used as the fixed rate going forward, with a stall detector monitoring the WebSocket rankings stream to detect when votes were being silently dropped.

## Features

- **Multi-threaded voting**: runs all sessions concurrently for maximum throughput.
- **Adaptive rate limiting**: automatically discovers and respects the server's hidden rate limits.
- **Proxy rotation**: distributes traffic across hundreds of Mullvad SOCKS5 proxies or a custom proxy.
- **Browser fingerprinting**: randomizes user agents and generates matching browser-specific headers.
- **Hold strategy**: locks the tile at a target rank by voting up or down to maintain the midpoint between neighbors.
- **Top-1 strategy**: races to first place then coasts with a configurable lead buffer.
- **Stall detection**: detects when votes are being silently dropped and pauses to let the limit window expire.
- **Persistence**: remembers session cooldowns and learned rates across restarts.
- **Forced direction**: manually override all strategies to vote exclusively up or down.

## Setup

```bash
uv sync
```

Place exported cookies (from [Cookie Quick Manager](https://github.com/ysard/cookie-quick-manager)) into `data/cookies.json`.

## Usage

See the [`.justfile`](.justfile) for predefined run targets, or run `uv run python -m autopaint -h` for all CLI options.
