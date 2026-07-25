"""Paper 5 diagnoser: run an LLM over evidence bundles and record its diagnosis.

Calls any OpenAI-compatible chat endpoint (llama.cpp server, vLLM, Ollama's
/v1) so the same harness serves every model. For each bundle it builds a
diagnosis prompt at a chosen evidence level (RQ2), asks the model for a
STRUCTURED answer (category, root_cause, fix, evidence_cited), and appends the
raw answer to results/<model>_<level>.jsonl. Grading is a separate,
deterministic step (rubric.py) so the model run is never contaminated by the
answer key.

Evidence levels (RQ2):
  full     -- describe + events + logs + workloads (+ webhooks)
  logs     -- logs only
  events   -- events only
  describe -- describe_pods only

Usage:
  python diagnose.py --base http://127.0.0.1:8000/v1 --model qwen2.5-14b \
      --level full --repeats 3
"""

import argparse
import json
import time
import urllib.request
from pathlib import Path

from corpus import by_id

HERE = Path(__file__).parent
BUNDLES = HERE / "bundles"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

TAXONOMY = ["scheduling", "image", "config", "probe", "resource", "storage",
            "network", "rbac", "admission", "gitops", "crash"]

SYSTEM = (
    "You are a senior Kubernetes SRE performing incident triage. You are given "
    "an evidence bundle captured from a cluster where exactly one fault has been "
    "injected. Identify the single ROOT CAUSE, not just the symptom. Base your "
    "answer only on the evidence provided; do not invent objects or logs that "
    "are not present. Respond with a single JSON object and nothing else."
)

INSTRUCT = """Analyze the evidence and return JSON with exactly these fields:
{{
  "category": one of {taxonomy},
  "root_cause": one or two sentences naming the specific misconfiguration or failure and WHY it causes the observed symptoms,
  "fix": the concrete remediation that resolves the root cause,
  "evidence_cited": a short list of the specific signals in the bundle that support your diagnosis
}}

EVIDENCE BUNDLE (scenario is unknown to you):
{evidence}
"""


def build_evidence(bundle, level):
    ev = bundle["evidence"]
    parts = [f"apply result: {bundle.get('apply_result','')}"]
    if level in ("full", "describe"):
        parts.append("== POD STATUS ==\n" + ev.get("pods", ""))
        parts.append("== DESCRIBE PODS ==\n" + ev.get("describe_pods", ""))
    if level in ("full", "events"):
        parts.append("== EVENTS ==\n" + ev.get("events", ""))
    if level in ("full", "logs"):
        lg = ev.get("logs", {})
        blob = []
        for pod, d in lg.items():
            blob.append(f"[{pod}] current:\n{d.get('current','')}\n"
                        f"[{pod}] previous:\n{d.get('previous','')}")
        parts.append("== LOGS ==\n" + "\n".join(blob))
    if level == "full":
        parts.append("== WORKLOADS/OBJECTS ==\n" + ev.get("workloads", ""))
        ann = ev.get("annotations", "").strip()
        if ann:
            parts.append("== DECLARED INTENT (spec.replicas + annotations) ==\n" + ann)
        wh = ev.get("webhooks", "").strip()
        if wh and "No resources" not in wh:
            parts.append("== ADMISSION WEBHOOKS ==\n" + wh)
    return "\n\n".join(p for p in parts if p.strip())


def call(base, model, system, user, timeout=180):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": 600,
    }).encode()
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    dt = time.perf_counter() - t0
    text = d["choices"][0]["message"]["content"]
    usage = d.get("usage", {})
    return text, dt, usage


def parse_json(text):
    """Extract the first JSON object from a model reply (tolerant)."""
    s = text.find("{")
    if s < 0:
        return None
    depth = 0
    for i in range(s, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[s:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="OpenAI-compatible base url, .../v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--level", default="full", choices=["full", "logs", "events", "describe"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--only", nargs="*", help="subset of scenario ids")
    a = ap.parse_args()

    ids = a.only or [p.stem for p in sorted(BUNDLES.glob("*.json"))]
    out = RESULTS / f"{a.model.replace('/', '_')}_{a.level}.jsonl"
    print(f"diagnosing {len(ids)} scenarios x {a.repeats} repeats -> {out.name}")

    with open(out, "a", encoding="utf-8") as f:
        for sid in ids:
            bundle = json.loads((BUNDLES / f"{sid}.json").read_text(encoding="utf-8"))
            user = INSTRUCT.format(taxonomy=TAXONOMY,
                                   evidence=build_evidence(bundle, a.level))
            for rep in range(a.repeats):
                try:
                    text, dt, usage = call(a.base, a.model, SYSTEM, user)
                    ans = parse_json(text)
                    rec = {"scenario_id": sid, "model": a.model, "level": a.level,
                           "repeat": rep, "latency_s": round(dt, 2),
                           "usage": usage, "parsed": ans, "raw": text}
                except Exception as e:
                    rec = {"scenario_id": sid, "model": a.model, "level": a.level,
                           "repeat": rep, "error": str(e)}
                f.write(json.dumps(rec) + "\n")
                f.flush()
                print(f"  {sid} r{rep}: "
                      + (rec.get("parsed", {}) or {}).get("category", rec.get("error", "?"))
                      if isinstance(rec.get("parsed"), dict) else f"  {sid} r{rep}: done")
    print("done")


if __name__ == "__main__":
    main()
