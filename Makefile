.PHONY: lint format test

lint:
	black --check .
	pylint --rcfile=.pylintrc $(shell git ls-files '*.py')

format:
	black .

test:
	pytest -vv
