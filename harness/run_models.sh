#!/usr/bin/env bash
# Paper 5 model runs on the VM. Assumes setup_vm.sh done, bundles/ captured.
# Runs every model at FULL evidence (RQ1), and one representative model at all
# four evidence levels (RQ2). Ollama serves OpenAI-compatible at :11434/v1.
set -uo pipefail
cd /root/harness
export OLLAMA_KEEP_ALIVE=10m
BASE=http://127.0.0.1:11434/v1

# size ladder of open models (fit a 24GB card); tag = ollama model name
MODELS=(
  "qwen2.5:7b-instruct"
  "llama3.1:8b-instruct-q4_K_M"
  "gemma2:9b-instruct-q4_K_M"
  "qwen2.5:14b-instruct"
  "qwen2.5:32b-instruct-q4_K_M"
)
RQ2_MODEL="qwen2.5:14b-instruct"

say(){ echo "[$(date -u +%H:%M:%S)] $*"; }

for M in "${MODELS[@]}"; do
  say "pull $M"
  ollama pull "$M" >/dev/null 2>&1 || { say "PULL FAILED $M"; continue; }
  say "RQ1 full: $M"
  python3 diagnose.py --base "$BASE" --model "$M" --level full --repeats 3 \
    >>/root/harness/run_models.log 2>&1 || say "diagnose full failed $M"
done

# RQ2: the representative model at the reduced evidence levels
for LV in logs events describe; do
  say "RQ2 $LV: $RQ2_MODEL"
  python3 diagnose.py --base "$BASE" --model "$RQ2_MODEL" --level "$LV" --repeats 3 \
    >>/root/harness/run_models.log 2>&1 || say "diagnose $LV failed"
done

say "ALL MODEL RUNS DONE"
ls -la /root/harness/results/
