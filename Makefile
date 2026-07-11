.PHONY: lint format test

PYTEST_ARGS ?= -vv

lint:
	./.venv/bin/ruff format --check .
	./.venv/bin/ruff check app main.py setup.py

format:
	./.venv/bin/ruff format .

test:
	./.venv/bin/pytest $(PYTEST_ARGS)
