# Technical Specification

## Vote API

### Endpoint

```
PUT https://please.paintastreet.com/tiles/{tile_id}/vote
```

### Request

Body: `{"direction": "up"}` or `{"direction": "down"}`

Common headers:

```
Accept: */*
Accept-Language: en-US,en;q=0.9
Accept-Encoding: gzip, deflate, br, zstd
Referer: https://paintastreet.com/
content-type: application/json
Origin: https://paintastreet.com
Connection: keep-alive
Sec-Fetch-Dest: empty
Sec-Fetch-Mode: cors
Sec-Fetch-Site: same-site
```

Browser-specific headers are added based on the User-Agent (see `useragent.py`):

- **Chrome**: `sec-ch-ua`, `sec-ch-ua-mobile`, `sec-ch-ua-platform`, `DNT: 1`, `Priority: u=1, i`
- **Firefox**: `Sec-GPC: 1`, `TE: trailers`, `Priority: u=0`

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

**429 Too Many Requests** — per-session rate limit (includes budget info):

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

**429 Too Many Requests** — per-tile rate limit (no budget info):

```json
{
  "error": "tile vote rate limit exceeded"
}
```

Neither 429 variant includes a `Retry-After` header.

## Rate Limits

### Per-session

10 votes per ~10 minute sliding window. The response includes `vote_budget.reset_at` (ISO 8601 UTC) and `vote_budget.window_seconds`.

### Per-tile (explicit)

A separate rate limit on the tile endpoint. Returns `{"error": "tile vote rate limit exceeded"}` with no timing info. Triggers when many sessions vote on the same tile in quick succession. Observed threshold: ~6-7 req/s across all sessions.

### Per-tile (silent)

An additional hidden rate limit that silently drops votes without returning 429. Detected by observing that the tile's vote count stops increasing despite successful 200 responses. The stall detector monitors this via the WebSocket.

## WebSocket Rankings

### Connection

```
wss://please.paintastreet.com/connection/websocket
```

Uses the Centrifugo protocol. No authentication required.

### Handshake

```json
→ {"id": 1, "connect": {}}
← {"id": 1, "connect": {"client": "...", "ping": 25, "pong": true}}
```

Server pings every 25s with `{}`, expects `{}` back.

### Rankings Subscription

```json
→ {"id": 2, "subscribe": {"channel": "rankings"}}
```

#### Initial Snapshot

```json
← {"id": 2, "subscribe": {"data": {"type": "rankings_snapshot", "seq": 15211, "tiles": [
    {"id": "tile-uuid", "vote_count": 9031},
    ...
]}}}
```

Contains all tiles with current vote counts.

#### Incremental Patches

```json
← {"push": {"channel": "rankings", "pub": {"data": {
    "type": "rankings_patch",
    "base_seq": 15211,
    "seq": 15212,
    "upserts": [
        {"id": "tile-uuid", "vote_count": 9032}
    ]
}}}}
```

Only contains tiles whose vote counts changed. Messages may be batched (multiple JSON objects separated by newlines in a single WebSocket frame).

## Cookies Format

JSON array exported from Firefox via [Cookie Quick Manager](https://github.com/ysard/cookie-quick-manager). Each entry must have:

```json
{
  "Content raw": "<session-token-hex-string>"
}
```

Other fields are ignored.

## Mullvad Proxies

Fetched from:

```
GET https://api.mullvad.net/public/relays/wireguard/v2
```

Active relays matching the configured country codes are selected. Hostnames are transformed: `ca-mtr-wg-001` → `socks5://ca-mtr-wg-socks5-001.relays.mullvad.net:1080`.

## Build System

- Build backend: [hatchling](https://hatch.pypa.io/)
- Version: dynamic, read from `autopaint/__init__.py`
- Dependencies: `requests[socks]`, `loguru`, `websockets`
- Test dependencies: `pytest`, `pytest-asyncio`
