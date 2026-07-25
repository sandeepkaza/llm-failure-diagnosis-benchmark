# cloud-failure-llm-benchmark

Companion artifact for the paper **"Can Open LLMs Diagnose Cloud-Native Failures? A Ground-Truth Benchmark from Injected Faults"**.

A ground-truth benchmark of 26 injected Kubernetes failures with known root causes, evidence bundles, and a deterministic grading rubric, evaluated against five open LLMs.

## What's here

`data/bundles/` — 26 sanitized evidence bundles (the labeled dataset). `harness/results/*.jsonl` — every per-answer record for 5 models x 3 repeats. `harness/corpus.py` — the fault corpus with answer keys. `harness/rubric.py` — deterministic grader (all 26 keys self-grade exact).

## Reproduce

Requires Python 3 (plus, per paper, Docker/kind/a GPU host — see the paper's
Method section). Every number in the paper is regenerated from the committed
data by:

```bash
cd harness && python3 corpus.py && python3 rubric.py   # validate corpus + rubric
python3 analyze.py                                       # RQ1-RQ4 from results/*.jsonl
```

Each stage writes its intermediate data, so the path from raw measurement to
every reported figure is inspectable without re-running the measurement.

## Citation

See `CITATION.cff`. A DOI will be added after Zenodo archival. Venue path:
IEEE CLOUD / AIOps workshop -> UCC -> IEEE Access.

## License

MIT (`LICENSE`). Author: Venkata Sandeep Chowdary Kaza <sandeep.kaza@gmail.com>, ORCID 0009-0001-9454-8995.

## AI-assistance disclosure

AI-assisted scripting and editing (Anthropic Claude) was employed under the
author's direction; the author defined the research questions, designed the
method, ran the measurements, and validated every reported number.
