# Paper 5 — "Can LLMs Diagnose Cloud-Native Failures? A Ground-Truth Benchmark from Injected Faults"

**Genre:** AIOps benchmark + evaluation (publishes a citable dataset).
**Venue path:** IEEE CLOUD / AIOps workshops → UCC → IEEE Access.
**Why intense/viral:** "LLM as SRE" is the loudest claim in ops right now with
no ground-truth benchmark behind it. We UNIQUELY have one: every failure this
program injects (Papers 2/3/7 harnesses) has a known root cause and a
log-backed evidence trail.

## RQs
- RQ1: Diagnosis accuracy — given the evidence bundle (events, pod status,
  controller logs, recent changes) for each injected failure, does the model
  identify the root cause? Graded rubric: exact / category / wrong /
  hallucinated. Models: Claude, GPT, Gemini, one local small model (RTX 3050)
  — pinned versions.
- RQ2: Evidence sensitivity — full bundle vs logs-only vs events-only vs
  truncated: what evidence do models actually need?
- RQ3: Remediation quality — proposed fix scored against the known-good fix
  (would it work? would it destroy data?); dangerous-advice rate.
- RQ4: Cost/latency — tokens + $ per correct diagnosis per model (FinOps
  angle even here).

## Fault corpus (ground truth we already own + rerun on kind)
Paper 3's findings (hostPath silent skip, restore-helper image, SC mismatch,
stale restore block...), Paper 2's (webhook fail-open, leftover webhooks),
Paper 7's (drift, broken manifest, repo unreachable), plus standard K8s
classics (OOMKill, crashloop, bad probe, image pull, DNS). Target ≥25 fault
scenarios × ≥3 evidence captures each; every bundle reproducible by script.

## Method notes
- Injection + capture harness on kind (bundle = kubectl describe/events/logs
  snapshot, sanitized).
- Blind grading rubric written BEFORE model runs; user validates rubric.
- Dataset + bundles published (the citable artifact — like Paper 2's corpus).

## Cost
LLM API calls ~$20–50; kind local. No GPU quota needed.

## Reframe (2026-07-24)
No LLM API keys available (OPENAI/ANTHROPIC/GEMINI absent from env) → run OPEN
models as diagnosers: "Can open LLMs diagnose cloud-native failures?" Qwen2.5
7B/14B/32B, Llama-3.1-8B, Gemma2-9B on a vast.ai RTX 4090. Frontier models
(Claude/GPT/Gemini) addable as a comparison leg if the user supplies keys.

## Status
- [x] Fault corpus (harness/corpus.py) — 26 scenarios, 11 categories,
      classic×20 + our-own P2/P3/P7×6; self-check passes
- [x] Capture harness (harness/capture.py) — sanitized evidence bundles
- [x] Diagnoser (harness/diagnose.py) — OpenAI-compatible, RQ2 evidence levels
- [x] **Rubric (harness/rubric.py) — deterministic, all 26 keys self-grade exact**
      → **USER REVIEWS RUBRIC before trusting numbers (plan requirement)**
- [x] Analyzer (harness/analyze.py) — RQ1/RQ2/RQ4 + by-category
- [x] Captured 26 bundles on vast VM k3s (data/bundles/ — citable dataset)
- [x] Model runs ×3 (5 models RQ1 full + qwen14b RQ2 4 levels); analysis.txt
- [x] results.md written (all RQs + gradings sample for rubric review)
- [x] **10pp draft COMPILED 2026-07-24** (paper.tex + refs.bib + title PDF);
      5 figs (fig_accuracy/category/evidence/scale + fig_pipeline.png), 6 tables
- [ ] **USER REVIEWS rubric.py + validates numbers vs results/*.jsonl**
- [ ] **USER reads refs.bib (none web-verified)**
- [ ] optional: add frontier models (Claude/GPT/Gemini) if keys supplied
- [ ] repo + dataset publish → Zenodo → IEEE CLOUD/AIOps venue

VM 45719079 DESTROYED. Cost ~$1.25. Two scenarios re-captured after
validation caught capture bugs (rbac shell-less image → curl-to-API;
drift needed annotations in bundle). Driver auto-upgrade mid-run fixed by
module reload (same as P6).
