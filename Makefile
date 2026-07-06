.PHONY: setup run run-monitor monitor clean

setup:
	bash ./scripts/setup.sh

run:
	poetry run python -B src/run_model.py \
		--model models/qwen3-0.6b \
		--prompt "Explique em português brasileiro o que é RAG em LLMs."

run-monitor:
	bash ./scripts/run_with_monitor.sh

monitor:
	poetry run python -B src/utils/monitor.py $(ARGS)

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
