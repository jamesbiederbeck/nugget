.PHONY: install-dev install test

install-dev:
	git fetch
	uv tool install --no-cache -e ".[web]" --force

install:
	uv pip install -e ".[dev]"

test:
	uv run pytest
