.PHONY: setup run web clean

setup:
	bash ./scripts/setup.sh

run:
	poetry run python -B src/norta_llm/run_model.py \
		--model models/qwen3-0.6b \
		--prompt "Explique em português brasileiro o que é RAG em LLMs."

web:
	PYTHONPATH=src poetry run python -B -m web_service.server

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
