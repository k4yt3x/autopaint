# Run the voter with default settings
run *args:
    uv run python -m autopaint -v {{ args }}

# Run with auto-rank holding top 5, resume at 7
run-hold *args:
    uv run python -m autopaint -v --auto-rank --rank-target 4 --rank-resume 5 {{ args }}

# Run racing to #1 with vote buffer
run-top1 *args:
    uv run python -m autopaint -v --top1 {{ args }}

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
