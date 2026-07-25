# Paper 5 — "Managed Kubernetes, Measured: Day-2 Operations Across Four Clouds"

**Genre:** controlled measurement study. **Venue path:** IEEE CLOUD → UCC → IEEE Access.
**Gap (web-verified 2026-07-18):** AKS/EKS/GKE comparisons are blog-grade
(claimed minutes, no method, no repetition); no rigorous cross-cloud
measurement of the operations customers actually pay the control-plane fee
for. We measure AKS vs EKS vs OKE vs GKE (all four accounts in hand; GKE project erudite-nation-492822-s3).

## RQs
- RQ1: Cluster provisioning time — decomposed (control plane vs node pool vs
  add-ons), n≥5 per cloud, same shape (2 small nodes).
- RQ2: Elasticity — node-pool scale-out latency (1→3 nodes; request → node
  Ready → pod schedulable), and scale-in behavior.
- RQ3: Upgrade — minor-version control-plane + node upgrade duration and
  workload disruption (boutique serving during upgrade; error/latency window
  measured by the sequenced probe).
- RQ4: Control-plane responsiveness — API p50/p95 under standardized load
  (list/create/watch churn), idle vs busy.
- RQ5 (FinOps): cost per operation — control-plane fees + node-hours consumed
  by each operation class, from metered bills.

## Method notes
- Reuse Paper 3 provisioning scripts + probe harness patterns; monotonic
  client-observed timestamps; medians + ranges over ≥5 trials.
- Same K8s minor version everywhere it's offered; document version skew as a
  finding (managed clouds gate different versions).
- Ops-findings log from day one (Paper 3 pattern paid off).

## Cost/discipline
2 small nodes/cloud, same-day teardown per campaign; upgrades measured on
throwaway clusters. Target <$40 total.

## Status
- [ ] Harness: provision/scale/upgrade timers (extend cloud/*.ps1)
- [ ] Runs ×5 per cloud per operation
- [ ] results.md → user validates → 10pp draft
