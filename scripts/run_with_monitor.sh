#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-models/qwen3-0.6b}"
PROMPT="${PROMPT:-Explique em português brasileiro o que é RAG em LLMs.}"
MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-300}"
LOG_DIR="${LOG_DIR:-logs}"
MONITOR_LOG_LINES="${MONITOR_LOG_LINES:-12}"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run-monitor-$(date +%Y%m%d-%H%M%S).log"

PYTHONUNBUFFERED=1 poetry run python -u -B src/run_model.py \
  --model "$MODEL" \
  --prompt "$PROMPT" \
  --max-new-tokens "$MAX_NEW_TOKENS" \
  >"$LOG_FILE" 2>&1 &

MODEL_PID="$!"

cleanup() {
  if kill -0 "$MODEL_PID" >/dev/null 2>&1; then
    kill "$MODEL_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup INT TERM EXIT

echo "Inferencia iniciada com PID $MODEL_PID"
echo "Saida do modelo: $LOG_FILE"
echo

poetry run python -B src/utils/monitor.py \
  --pid "$MODEL_PID" \
  --exit-when-pid-exits \
  --log-file "$LOG_FILE" \
  --log-lines "$MONITOR_LOG_LINES"

wait "$MODEL_PID" || {
  status="$?"
  echo
  echo "Inferencia encerrou com erro. Veja o log: $LOG_FILE"
  exit "$status"
}

trap - INT TERM EXIT

echo
echo "Inferencia finalizada. Veja a resposta em: $LOG_FILE"
