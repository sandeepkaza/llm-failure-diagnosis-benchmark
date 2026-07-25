"""Paper 5 figures (vector PDF, IEEE single-column 3.5in).

Reads results/*.jsonl, grades with the deterministic rubric, and emits:
Fig 1 fig_accuracy.pdf   -- per-model exact/category/wrong/hallucinated stacked bars (RQ1)
Fig 2 fig_category.pdf   -- accuracy by fault category, pooled (the loud-vs-quiet finding)
Fig 3 fig_evidence.pdf   -- RQ2 accuracy vs evidence level (representative model)
Fig 4 fig_scale.pdf      -- accuracy vs model size (the scaling trend)
Run: python make_figures.py   (from harness/, after results exist)
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from corpus import by_id, SCENARIOS
from rubric import grade_answer

HERE = Path(__file__).parent
RESULTS = HERE / "results"

# Okabe-Ito, ordered exact->hallucinated (green good -> red bad)
C_EXACT, C_CAT, C_WRONG, C_HALL = "#009E73", "#56B4E9", "#E69F00", "#D55E00"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d9d8d3"
plt.rcParams.update({
    "font.size": 7.5, "axes.labelsize": 7.5, "axes.titlesize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 6.8,
    "font.family": "serif", "axes.edgecolor": MUTED, "axes.linewidth": 0.6,
    "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "axes.labelcolor": INK, "pdf.fonttype": 42,
})

# approx parameter sizes (B) for the scaling figure
SIZE = {"qwen2.5:7b-instruct": 7, "llama3.1:8b-instruct-q4_K_M": 8,
        "gemma2:9b-instruct-q4_K_M": 9, "qwen2.5:14b-instruct": 14,
        "qwen2.5:32b-instruct-q4_K_M": 32}
SHORT = {"qwen2.5:7b-instruct": "Qwen2.5-7B", "llama3.1:8b-instruct-q4_K_M": "Llama3.1-8B",
         "gemma2:9b-instruct-q4_K_M": "Gemma2-9B", "qwen2.5:14b-instruct": "Qwen2.5-14B",
         "qwen2.5:32b-instruct-q4_K_M": "Qwen2.5-32B"}
LABELS = ["exact", "category", "wrong", "hallucinated"]
LC = {"exact": C_EXACT, "category": C_CAT, "wrong": C_WRONG, "hallucinated": C_HALL}


def load_graded():
    rows = []
    for f in sorted(RESULTS.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    out = []
    for r in rows:
        try:
            s = by_id(r["scenario_id"])
        except KeyError:
            continue
        out.append({**r, "label": grade_answer(s, r.get("parsed"))["label"]})
    return out


def majority(labels):
    order = {"exact": 0, "category": 1, "wrong": 2, "hallucinated": 3}
    c = Counter(labels)
    top = max(c.values())
    return max([l for l, n in c.items() if n == top], key=lambda l: order[l])


def model_scen_labels(graded, level="full"):
    per = defaultdict(list)
    for r in graded:
        if r.get("level") == level:
            per[(r["model"], r["scenario_id"])].append(r["label"])
    msl = defaultdict(dict)
    for (m, sid), labs in per.items():
        msl[m][sid] = majority(labs)
    return msl


def main():
    graded = load_graded()
    if not graded:
        print("no results yet"); return
    msl = model_scen_labels(graded, "full")
    models = [m for m in SIZE if m in msl] or sorted(msl)

    # ---- Fig 1: per-model stacked accuracy ----
    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    y = range(len(models))
    for i, m in enumerate(models):
        c = Counter(msl[m].values()); n = sum(c.values())
        left = 0
        for lab in LABELS:
            w = 100 * c[lab] / n
            ax.barh(i, w, left=left, color=LC[lab], height=0.62,
                    label=lab if i == 0 else None)
            if w > 8:
                ax.annotate(f"{w:.0f}", (left + w / 2, i), ha="center", va="center",
                            fontsize=6, color="white")
            left += w
    ax.set_yticks(list(y), [SHORT.get(m, m) for m in models], fontsize=6.6)
    ax.set_xlabel("Share of scenarios (%)")
    ax.set_xlim(0, 100)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper center", ncol=4, bbox_to_anchor=(0.5, -0.22), fontsize=6)
    ax.set_title("RQ1: diagnosis outcome per model (full evidence)", fontsize=7)
    fig.tight_layout(); fig.savefig("fig_accuracy.pdf"); print("fig_accuracy.pdf")

    # ---- Fig 2: by category (loud vs quiet) ----
    cat_of = {s.id: s.category for s in SCENARIOS}
    per_cat = defaultdict(lambda: [0, 0])
    for m in models:
        for sid, lab in msl[m].items():
            per_cat[cat_of[sid]][1] += 1
            if lab in ("exact", "category"):
                per_cat[cat_of[sid]][0] += 1
    cats = sorted(per_cat, key=lambda c: per_cat[c][0] / max(per_cat[c][1], 1))
    vals = [100 * per_cat[c][0] / max(per_cat[c][1], 1) for c in cats]
    fig, ax = plt.subplots(figsize=(3.5, 2.6))
    cols = [C_WRONG if v < 40 else (C_CAT if v < 80 else C_EXACT) for v in vals]
    ax.barh(range(len(cats)), vals, color=cols, height=0.66)
    for i, (c, v) in enumerate(zip(cats, vals)):
        ax.annotate(f"{v:.0f}%", (v + 1, i), va="center", fontsize=6, color=MUTED)
    ax.set_yticks(range(len(cats)), cats, fontsize=6.6)
    ax.set_xlabel("Correct (exact+category) %, all models pooled")
    ax.set_xlim(0, 108)
    ax.spines[["top", "right"]].set_visible(False)
    ax.xaxis.grid(True, linewidth=0.3, color=GRID); ax.set_axisbelow(True)
    ax.set_title("RQ1: loud faults solved, quiet faults missed", fontsize=7)
    fig.tight_layout(); fig.savefig("fig_category.pdf"); print("fig_category.pdf")

    # ---- Fig 3: RQ2 evidence level (representative model) ----
    rq2m = "qwen2.5:14b-instruct"
    levels = ["full", "logs", "events", "describe"]
    accs = []
    for lv in levels:
        m2 = model_scen_labels(graded, lv).get(rq2m, {})
        if m2:
            ok = sum(1 for l in m2.values() if l in ("exact", "category"))
            accs.append(100 * ok / len(m2))
        else:
            accs.append(None)
    fig, ax = plt.subplots(figsize=(3.5, 2.1))
    xs = [i for i, a in enumerate(accs) if a is not None]
    ys = [a for a in accs if a is not None]
    ax.bar(xs, ys, color=C_CAT, width=0.6)
    for x, a in zip(xs, ys):
        ax.annotate(f"{a:.0f}%", (x, a), ha="center", va="bottom", fontsize=6.5, color=MUTED)
    ax.set_xticks(range(len(levels)), levels)
    ax.set_ylabel("Correct %")
    ax.set_title(f"RQ2: evidence sensitivity ({SHORT.get(rq2m, rq2m)})", fontsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, linewidth=0.3, color=GRID); ax.set_axisbelow(True)
    fig.tight_layout(); fig.savefig("fig_evidence.pdf"); print("fig_evidence.pdf")

    # ---- Fig 4: accuracy vs model size ----
    fig, ax = plt.subplots(figsize=(3.5, 2.1))
    pts = []
    for m in models:
        c = Counter(msl[m].values()); n = sum(c.values())
        acc = 100 * (c["exact"] + c["category"]) / n
        pts.append((SIZE[m], acc, SHORT.get(m, m)))
    pts.sort()
    ax.plot([p[0] for p in pts], [p[1] for p in pts], "o-", color=C_EXACT, linewidth=1.4)
    for sz, acc, name in pts:
        ax.annotate(name.split("-")[-1], (sz, acc), fontsize=5.8, color=MUTED,
                    xytext=(2, 3), textcoords="offset points")
    ax.set_xlabel("Model size (B params)")
    ax.set_ylabel("Correct % (full)")
    ax.set_title("RQ1: accuracy vs scale", fontsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(True, linewidth=0.3, color=GRID); ax.set_axisbelow(True)
    fig.tight_layout(); fig.savefig("fig_scale.pdf"); print("fig_scale.pdf")

    print("\n[check] models:", [SHORT.get(m, m) for m in models])


if __name__ == "__main__":
    main()
