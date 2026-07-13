.PHONY: install test publish dashboard review worker
install:
	python -m pip install -e ".[dev,pdf]"
test:
	python -m pytest
publish:
	python -m olkalou_engine.cli --root . publish --simulations 1000
dashboard:
	python -m olkalou_engine.cli --root . serve-static --host 0.0.0.0 --port 8000
review:
	python -m olkalou_engine.cli --root . review --host 0.0.0.0 --port 8080
worker:
	python -m olkalou_engine.cli --root . worker
