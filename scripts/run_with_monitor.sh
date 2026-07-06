#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-models/qwen3-0.6b}"
PROMPT="${PROMPT:-Explique em português brasileiro o que é RAG em LLMs.}"
MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-300}"
LOG_ROOT="${LOG_ROOT:-logs/runs}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
MONITOR_LOG_LINES="${MONITOR_LOG_LINES:-12}"

RUN_DIR="$LOG_ROOT/$RUN_ID"
LOG_FILE="$RUN_DIR/console.log"
METRICS_FILE="$RUN_DIR/metrics.jsonl"
SUMMARY_FILE="$RUN_DIR/summary.json"
STATUS_FILE="$RUN_DIR/status.txt"
RUN_ENV_FILE="$RUN_DIR/run.env"

mkdir -p "$RUN_DIR"

cat >"$RUN_ENV_FILE" <<EOF
RUN_ID=$RUN_ID
MODEL=$MODEL
PROMPT=$PROMPT
MAX_NEW_TOKENS=$MAX_NEW_TOKENS
STARTED_AT=$(date -Iseconds)
EOF
echo "running" >"$STATUS_FILE"

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

echo "Execucao: $RUN_ID"
echo "Inferencia iniciada com PID $MODEL_PID"
echo "Saida do modelo: $LOG_FILE"
echo "Metricas: $METRICS_FILE"
echo "Resumo: $SUMMARY_FILE"
echo

poetry run python -B src/utils/monitor.py \
  --pid "$MODEL_PID" \
  --exit-when-pid-exits \
  --log-file "$LOG_FILE" \
  --log-lines "$MONITOR_LOG_LINES" \
  --run-id "$RUN_ID" \
  --metrics-file "$METRICS_FILE" \
  --summary-file "$SUMMARY_FILE"

wait "$MODEL_PID" || {
  status="$?"
  echo "failed:$status" >"$STATUS_FILE"
  echo
  echo "Inferencia encerrou com erro. Veja o log: $LOG_FILE"
  exit "$status"
}

trap - INT TERM EXIT
echo "completed" >"$STATUS_FILE"

echo
echo "Inferencia finalizada."
echo "Arquivos da execucao: $RUN_DIR"
