.PHONY: setup run monitor clean

setup:
	bash ./scripts/setup.sh

run:
	bash ./scripts/run.sh

monitor:
	poetry run python -B src/utils/monitor.py $(ARGS)

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
