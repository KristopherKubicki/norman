.PHONY: lint format test

lint:
	./.venv/bin/ruff format --check .
	./.venv/bin/ruff check app main.py setup.py

format:
	./.venv/bin/ruff format .

test:
	pytest -vv
