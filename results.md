# Paper 5 results — open-LLM cloud-native failure diagnosis (validation source)

**Status: ALL DATA COMPLETE 2026-07-24.** 26 ground-truth fault scenarios,
5 open models, 3 repeats, deterministic rubric. Data in `harness/results/*.jsonl`
(606 answers total: 390 full-evidence = 5 models x 26 scenarios x 3 repeats,
plus 216 RQ2-level = 3 levels x 24 scenarios x 3 repeats), `data/bundles/*.json` (26 evidence
bundles = the citable dataset), `analysis.txt` (analyze.py output).
**USER VALIDATES the rubric (harness/rubric.py) and these numbers before drafting.**

## Reframe
No LLM API keys available → ran OPEN models as diagnosers on a vast.ai RTX 4090
(k3s for fault injection + Ollama for inference). Frontier models
(Claude/GPT/Gemini) are addable as a comparison leg if keys are supplied — the
harness is model-agnostic.

## Testbed
- k3s v1.36 on a vast.ai KVM VM (RTX 4090 24GB). 26 faults injected, evidence
  captured (kubectl describe/events/logs/workloads/annotations, sanitized),
  namespace torn down between scenarios.
- Models via Ollama /v1: Qwen2.5-7B, Llama-3.1-8B, Gemma2-9B, Qwen2.5-14B,
  Qwen2.5-32B-Q4. Temperature 0, structured JSON answer (category, root_cause,
  fix, evidence_cited). 3 repeats, majority vote.
- Grading: deterministic rubric (concept-group + forbidden-token match), all 26
  answer keys self-grade "exact". Labels: exact / category / wrong / hallucinated.
  **Mechanism-correct (MECH)** = root cause identified (rootcause_grade exact or
  partial) and not a hallucination, REGARDLESS of the coarse category label.

## RQ1 — diagnosis accuracy (full evidence, majority vote, n=26)

| model | exact | category | wrong | halluc | **MECH** |
|---|---|---|---|---|---|
| Gemma2-9B | 57.7% | 7.7% | 26.9% | 7.7% | **88%** |
| Qwen2.5-7B | 61.5% | 3.8% | 34.6% | 0% | **88%** |
| Llama-3.1-8B | 61.5% | 7.7% | 23.1% | 7.7% | **92%** |
| Qwen2.5-14B | 69.2% | 0% | 30.8% | 0% | **96%** |
| Qwen2.5-32B | 73.1% | 11.5% | 15.4% | 0% | **100%** |

**Headline finding:** open LLMs identify the root-cause MECHANISM 88–100% of the
time (Qwen-32B 100%), but strict category-matched "exact" scoring reports only
58–73%. **The gap is taxonomy disagreement, not diagnostic failure** — models
correctly name the mechanism but assign a different coarse category than the
fixed 11-way taxonomy on ambiguous fault classes. Reporting only the strict
number would understate LLM diagnostic ability by ~25–30 points. Clear scale
trend: Qwen 7B→14B→32B mechanism 88→96→100%, exact 62→69→73%.

## RQ1 by category (exact+category %, all models pooled) — loud vs quiet

| category | correct | note |
|---|---|---|
| image | 15/15 (100%) | loud |
| resource | 10/10 (100%) | loud |
| admission | 10/10 (100%) | loud (P2 webhooks) |
| storage | 10/10 (100%) | loud (P3 DR) |
| rbac | 5/5 (100%) | 403 in logs |
| probe | 8/10 (80%) | |
| config | 18/25 (72%) | |
| scheduling | 9/15 (60%) | often labeled "resource" |
| network | 6/10 (60%) | |
| crash | 1/15 (7%) | **category artifact** — MECH high, models say "probe" |
| gitops | 0/5 (0%) | **category artifact** — models diagnose drift, label "config" |

The crash (7%) and gitops (0%) collapses are NOT diagnostic failures: the
gradings sample below shows models correctly identify the mechanism in both;
they disagree with the taxonomy label (crash→probe, gitops-drift→config). This
is why MECH is the fairer primary metric.

## RQ2 — evidence sensitivity (Qwen2.5-14B, exact+category %, n=24*)

| evidence level | correct % |
|---|---|
| full (describe+events+logs+workloads) | 69% |
| logs only | **46%** |
| events only | 71% |
| describe only | 71% |

**Finding:** raw LOGS alone are the LEAST diagnostic single evidence source
(46%, below full), while structured status — events-only OR describe-only — each
nearly matches full evidence (71%). For these failure classes the diagnosis
lives in the object status and events, not in application logs. A triage tool
feeding an LLM should prioritize `describe`/`events` over log dumps.
\*RQ2 levels run on 24 scenarios (rbac+drift excluded during their re-capture).

## RQ4 — cost/latency per correct diagnosis (full)

| model | med latency | tot tokens | tok/correct | correct% |
|---|---|---|---|---|
| Qwen2.5-7B | 1.25 s | 159,808 | 3,133 | 65% |
| Llama-3.1-8B | 1.59 s | 149,663 | 2,772 | 69% |
| Qwen2.5-14B | 1.92 s | 159,504 | 2,954 | 69% |
| Gemma2-9B | 2.79 s | 151,243 | 2,966 | 65% |
| Qwen2.5-32B | 22.23 s | 160,396 | 2,468 | 83% |

**Finding:** the 32B model is the most token-efficient per correct diagnosis
(2,468 tok) and most accurate, but 12–18× slower per call (22s vs 1–3s). Small
models are near-instant at a modest accuracy cost — a real latency/accuracy
FinOps tradeoff for an always-on triage assistant.

## Sample gradings (for USER rubric review — one per category, Qwen-14B)

| category | scenario | llm_cat | label | MECH | llm root cause (excerpt) |
|---|---|---|---|---|---|
| probe | badprobe | probe | exact | Y | readiness probe checks 8080, nginx listens 80 |
| resource | oomkill | resource | exact | Y | container exceeds 64Mi limit, OOMKilled |
| image | imagepull-badtag | image | exact | Y | image tag does-not-exist-9x9 absent |
| rbac | rbac-forbidden | rbac | exact | Y | SA 'lister' lacks permission to list pods |
| admission | p2-leftover-webhook | admission | exact | Y | leftover validating webhook blocking creates |
| storage | p3-sc-mismatch | storage | exact | Y | PVC references nonexistent StorageClass |
| network | dns-wrong-svc | network | exact | Y | DNS for backend-service fails, no such svc |
| config | crashloop-missing-dep | config | exact | Y | ConfigMap volume mount refers missing key |
| scheduling | cpu-throttle-pending | resource | **wrong** | Y | requests 64 CPU exceeds available — *mech right, cat "resource" not "scheduling"* |
| crash | crashloop-cmd | probe | **wrong** | Y | command exits immediately, restart loop — *mech right, cat "probe" not "crash"* |
| gitops | p7-drift-scaled | config | **wrong** | Y | desired replicas 1 in annotations but actual is 4 — *drift correctly diagnosed, cat "config" not "gitops"* |

Every "wrong" in the sample is a category disagreement on an ambiguous fault;
the mechanism is correct in all 11. This is the paper's central methodological
point and the reason MECH is reported as primary.

## Threats / notes
- Category taxonomy is coarse and ambiguous at boundaries (scheduling/resource,
  crash/probe, gitops/config); strict category scoring penalizes reasonable
  disagreement. We report MECH (mechanism) as primary and category as secondary.
- Rubric is deterministic and published; concept groups are a judgment call →
  USER reviews. All 26 answer keys self-grade "exact" (calibration check).
- Open models only (no API keys); single prompt template; 3 repeats.
- 2 scenarios were re-captured after validation caught capture bugs (rbac image
  had no shell → curl-to-API; drift needed annotations in the bundle). Honest
  final data reflects the fixes.
- Cost: ~$1.25 vast.ai (RTX 4090 ~3.5h).
