# Max votes at fixed rate with stall detection, no rank strategy
run *args:
    uv run python -m autopaint -v --rate 6 {{ args }}

# Run with auto-rank holding top 5, resume at 7
run-hold *args:
    uv run python -m autopaint -v --auto-rank --rank-target 3 --rank-resume 4 {{ args }}

# Run racing to #1 with vote buffer
run-top1 *args:
    uv run python -m autopaint -v --top1 {{ args }}

# Run without throttle (respects 429s and cooldowns)
run-fast *args:
    uv run python -m autopaint -v --no-throttle {{ args }}

# Run with no rate limiting (spam mode, ignores everything)
run-spam *args:
    uv run python -m autopaint -v --no-ratelimit --no-auto-rank {{ args }}

# Downvote a target tile with separate cookies/db
run-mit *args:
    uv run python -m autopaint -v --rate 14 --direction down -t 019d4f98-84cd-776c-ac4c-2ea3092e658e -c data/cookies.1.json --db data/autopaint.1.db {{ args }}

# Downvote a target tile with no rate limiting
run-mit-fast *args:
    uv run python -m autopaint -v --no-throttle --direction down -t 019d4f98-84cd-776c-ac4c-2ea3092e658e -c data/cookies.1.json --db data/autopaint.1.db {{ args }}

# Install/sync dependencies
sync:
    uv sync

# Format code with black
fmt:
    uv run black autopaint/

# Lint with ruff
lint:
    uv run ruff check autopaint/

# Run tests
test:
    uv run pytest tests/
