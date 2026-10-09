.PHONY: test syntax image

test:
	PYTHONPATH=src python -m pytest

syntax:
	python -m compileall -q src

image:
	docker build -t expert-memory-market:local .
