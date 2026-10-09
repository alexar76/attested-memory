.PHONY: test syntax image

test:
	PYTHONPATH=src python -m pytest

syntax:
	python -m compileall -q src

image:
	docker build -t personal-attested-memory:local .
