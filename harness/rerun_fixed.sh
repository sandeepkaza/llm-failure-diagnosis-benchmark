#!/usr/bin/env bash
# Re-capture and re-diagnose only the scenarios whose CAPTURE was fixed
# (rbac-forbidden: pullable image; p7-drift-scaled: annotations now in bundle).
# Strips stale answers for those scenarios from each model's jsonl first so the
# analysis is not double-counted. broken-manifest needs no re-run (grading-only
# category fix).
set -uo pipefail
cd /root/harness
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
BASE=http://127.0.0.1:11434/v1
FIXED="rbac-forbidden p7-drift-scaled"

echo "== re-capture fixed scenarios =="
python3 capture.py $FIXED

echo "== strip stale answers for fixed scenarios =="
for f in results/*.jsonl; do
  python3 - "$f" $FIXED <<'PY'
import json,sys
path=sys.argv[1]; fixed=set(sys.argv[2:])
keep=[l for l in open(path) if json.loads(l).get("scenario_id") not in fixed]
open(path,"w").writelines(keep)
PY
done

MODELS=(
  "qwen2.5:7b-instruct"
  "llama3.1:8b-instruct-q4_K_M"
  "gemma2:9b-instruct-q4_K_M"
  "qwen2.5:14b-instruct"
  "qwen2.5:32b-instruct-q4_K_M"
)
for M in "${MODELS[@]}"; do
  echo "== re-run $M on fixed =="
  python3 diagnose.py --base "$BASE" --model "$M" --level full --repeats 3 --only $FIXED \
    >>/root/harness/rerun.log 2>&1 || echo "rerun failed $M"
done
echo "RERUN DONE"
