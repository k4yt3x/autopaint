# Technical Specification

## API

### Endpoint

```
PUT https://please.paintastreet.com/tiles/{tile_id}/vote
```

### Request

Body: `{"direction": "up"}`

Required headers (beyond User-Agent and Cookie):

```
Accept: */*
Accept-Language: en-US,en;q=0.9
Accept-Encoding: gzip, deflate, br, zstd
Referer: https://paintastreet.com/
content-type: application/json
Origin: https://paintastreet.com
Sec-GPC: 1
Connection: keep-alive
Sec-Fetch-Dest: empty
Sec-Fetch-Mode: cors
Sec-Fetch-Site: same-site
Priority: u=0
TE: trailers
```

### Responses

**200 OK** (successful vote):

```json
{
  "vote_budget": {
    "limit": 10,
    "remaining": 9,
    "reset_at": "2026-04-05T00:10:34.597796245Z",
    "window_seconds": 595
  }
}
```

**429 Too Many Requests** - per-session rate limit (includes budget info):

```json
{
  "error": "vote rate limit exceeded",
  "vote_budget": {
    "limit": 10,
    "remaining": 0,
    "reset_at": "2026-04-05T00:10:34.598082049Z",
    "window_seconds": 595
  }
}
```

**429 Too Many Requests** - per-tile rate limit (no budget info):

```json
{
  "error": "tile vote rate limit exceeded"
}
```

Note: neither 429 variant includes a `Retry-After` header.

## Rate Limits

There are two independent rate limits:

1. **Per-session**: 10 votes per ~10 minute window. The server returns `vote_budget.reset_at` (ISO 8601 UTC timestamp) and `vote_budget.window_seconds` in both 200 and 429 responses. The `remaining` field counts down from `limit` to 0.

2. **Per-tile**: A separate rate limit on the tile itself, likely per-IP. Returns only `{"error": "tile vote rate limit exceeded"}` with no timing information. This triggers when many sessions vote on the same tile in quick succession.

### Rate-Limit Strategy

- **Per-session 429 or `remaining == 0`**: Parse `reset_at` from the response body, compute `reset_at - now + 1s`, and sleep that duration. Falls back to `window_seconds + 1s`, then to 600s.
- **Per-tile 429**: Back off with random jitter (5-15s) and retry. No budget info is available, so the retry is short and randomized to naturally stagger threads.

## Cookies Format

The `data/cookies.json` file is a JSON array of cookie objects exported from Firefox using [Cookie Quick Manager](https://github.com/ysard/cookie-quick-manager). Each object must have at least:

```json
{
  "Content raw": "<session-token-hex-string>"
}
```

Other fields (`Host raw`, `Name raw`, `Expires`, `Store raw`, etc.) are ignored by the program.

## User Agents

On startup, a list of user agent strings is fetched from:

```
https://raw.githubusercontent.com/MichaelJorky/top-user-agents-latest/refs/heads/main/data/browsers/browsers_1.txt
```

Each voter thread is assigned one random UA at startup (fixed for the thread's lifetime).

## SOCKS5 Proxies

By default, each voter thread routes traffic through a random Mullvad SOCKS5 proxy. Proxies are fetched at startup from the Mullvad relay API:

```
GET https://api.mullvad.net/public/relays/wireguard/v2
```

The response contains a `wireguard.relays` array. Active relays whose `location` starts with the configured country code (default `ca`) are selected. The hostname is transformed from `wg-` to `wg-socks5-` and suffixed with `.relays.mullvad.net:1080` to form the SOCKS5 address.

Example: relay hostname `ca-mtr-wg-001` becomes `socks5://ca-mtr-wg-socks5-001.relays.mullvad.net:1080`.

Each thread gets one random proxy at startup (fixed for the thread's lifetime). Proxying can be disabled with `--no-proxy`, and the country code can be changed with `--proxy-country`. Available country codes include: `al`, `ar`, `at`, `au`, `be`, `bg`, `br`, `ca`, `ch`, `cl`, `co`, `cy`, `cz`, `de`, `dk`, `ee`, `es`, `fi`, `fr`, `gb`, `gr`, `hk`, `hr`, `hu`, `id`, `ie`, `il`, `it`, `jp`, `mx`, `my`, `ng`, `nl`, `no`, `nz`, `pe`, `ph`, `pl`, `pt`, `ro`, `rs`, `se`, `sg`, `si`, `sk`, `th`, `tr`, `ua`, `us`, `za`.

Requires `requests[socks]` (PySocks) for SOCKS5 support.

## Threading Model

- One `threading.Thread(daemon=True)` per session cookie.
- All threads share no mutable state (each `Voter` instance is independent).
- The main thread joins all worker threads and exits on `KeyboardInterrupt`.
- Threads naturally stagger over time due to independent rate-limit windows and jitter on tile-level 429 retries.

## Build System

- Build backend: [hatchling](https://hatch.pypa.io/)
- Version: dynamic, read from `autopaint/__init__.py` (`__version__` variable)
- Dependencies: `requests[socks]`, `loguru`
