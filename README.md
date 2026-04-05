# Autopaint

Automated voting tool for [paintastreet.com](https://paintastreet.com/). Runs one voter thread per session cookie, with random user agents, SOCKS5 proxies via Mullvad, and server rate-limit handling.

## Requirements

- Python >= 3.14
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
```

Place your exported cookies into `data/cookies.json`. See [docs/SPEC.md](docs/SPEC.md) for the expected format.

## Usage

```bash
# Run with defaults (Mullvad proxy enabled, Canada)
uv run python -m autopaint

# Use US proxies
uv run python -m autopaint --proxy-country us

# Disable proxying
uv run python -m autopaint --no-proxy

# Custom cookies file and tile ID
uv run python -m autopaint -c data/cookies.json -t <tile-id>

# Verbose logging
uv run python -m autopaint -v
```

### CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `-c`, `--cookies` | `data/cookies.json` | Path to cookies JSON file |
| `-t`, `--tile-id` | `019d589b-...` | Tile ID to vote on |
| `--no-proxy` | `false` | Disable SOCKS5 proxy via Mullvad |
| `--proxy-country` | `ca` | Mullvad proxy country code |
| `-v`, `--verbose` | `false` | Enable debug logging |

## Project Structure

```
autopaint/
  __init__.py       # Package version
  __main__.py       # CLI entry point
  voter.py          # Voter class and HTTP logic
data/
  cookies.json      # Session cookies (gitignored)
docs/
  SPEC.md           # Technical specification
```
