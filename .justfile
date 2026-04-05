# Run the voter with default settings
run *args:
    uv run python -m autopaint -v {{ args }}

# Run with verbose logging
run-verbose *args:
    uv run python -m autopaint -v {{ args }}

# Run with auto-rank holding 3rd place
run-hold *args:
    uv run python -m autopaint -v --auto-rank {{ args }}

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
