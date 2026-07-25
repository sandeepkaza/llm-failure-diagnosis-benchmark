"""Paper 5 analysis: grade every model answer and aggregate the RQs.

Reads results/*.jsonl (from diagnose.py), grades each with the deterministic
rubric (rubric.py), and prints:
  RQ1 -- per-model diagnosis accuracy at the full evidence level (exact /
         category / wrong / hallucinated rates), majority-vote over repeats.
  RQ2 -- per-model accuracy by evidence level (full/logs/events/describe).
  RQ4 -- tokens and latency per correct diagnosis per model.
Plus a per-category breakdown (which fault classes are hard for everyone).

Usage: python analyze.py            # all results/*.jsonl
"""

import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

from corpus import by_id, SCENARIOS
from rubric import grade_answer

HERE = Path(__file__).parent
RESULTS = HERE / "results"
LABELS = ["exact", "category", "wrong", "hallucinated"]


def load():
    rows = []
    for f in sorted(RESULTS.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def majority_label(labels):
    """Most-common grade over repeats; ties break toward the worse outcome."""
    order = {"exact": 0, "category": 1, "wrong": 2, "hallucinated": 3}
    c = Counter(labels)
    top = max(c.values())
    tied = [l for l, n in c.items() if n == top]
    return max(tied, key=lambda l: order[l])


def graded_rows(rows):
    """Attach a rubric grade to each answer row that has a parse."""
    out = []
    for r in rows:
        if "parsed" not in r and "error" not in r:
            continue
        try:
            s = by_id(r["scenario_id"])
        except KeyError:
            continue
        g = grade_answer(s, r.get("parsed"))
        out.append({**r, "grade": g})
    return out


def rq1(graded):
    print("=" * 72)
    print("RQ1 -- diagnosis accuracy at FULL evidence (majority vote over repeats)")
    print("=" * 72)
    # (model, scenario) -> [labels across repeats], full level only
    per = defaultdict(list)
    per_mech = defaultdict(list)   # mechanism (root cause) grade, ignoring category
    for r in graded:
        if r.get("level") != "full":
            continue
        per[(r["model"], r["scenario_id"])].append(r["grade"]["label"])
        rc = r["grade"].get("rootcause_grade", "wrong")
        hall = r["grade"].get("hallucinated", False)
        # mechanism-correct = identified root cause (exact/partial) and not a
        # hallucination -- regardless of the coarse category label.
        per_mech[(r["model"], r["scenario_id"])].append(
            "mech" if (rc in ("exact", "partial") and not hall) else "no")
    models = sorted({m for m, _ in per})
    print(f"{'model':<26}" + "".join(f"{l:>12}" for l in LABELS)
          + f"{'MECH':>8}{'n':>4}")
    model_scen_label = defaultdict(dict)
    for m in models:
        scen_labels = {sid: majority_label(per[(m, sid)])
                       for (mm, sid) in per if mm == m}
        model_scen_label[m] = scen_labels
        c = Counter(scen_labels.values())
        n = len(scen_labels)
        # mechanism accuracy: fraction of scenarios where majority repeat is mech
        mech = 0
        for (mm, sid) in per_mech:
            if mm == m:
                mech += 1 if Counter(per_mech[(mm, sid)]).most_common(1)[0][0] == "mech" else 0
        print(f"{m:<26}" + "".join(f"{100*c[l]/n:>10.1f}%" for l in LABELS)
              + f"{100*mech/n:>6.0f}%{n:>4}")
    return model_scen_label


def rq1_by_category(graded, model_scen_label):
    print("\n" + "=" * 72)
    print("RQ1 -- exact+category accuracy by fault category (all models pooled)")
    print("=" * 72)
    cat_of = {s.id: s.category for s in SCENARIOS}
    per_cat = defaultdict(lambda: [0, 0])  # cat -> [correct, total]
    for m, scen in model_scen_label.items():
        for sid, lab in scen.items():
            per_cat[cat_of[sid]][1] += 1
            if lab in ("exact", "category"):
                per_cat[cat_of[sid]][0] += 1
    for cat, (ok, tot) in sorted(per_cat.items(), key=lambda kv: kv[1][0] / max(kv[1][1], 1)):
        print(f"  {cat:<12} {ok:>3}/{tot:<3} correct ({100*ok/max(tot,1):.0f}%)")


def rq2(graded):
    print("\n" + "=" * 72)
    print("RQ2 -- accuracy by evidence level (exact+category %, majority vote)")
    print("=" * 72)
    per = defaultdict(list)  # (model, level, scenario) -> labels
    for r in graded:
        per[(r["model"], r.get("level"), r["scenario_id"])].append(r["grade"]["label"])
    levels = ["full", "logs", "events", "describe"]
    models = sorted({m for m, _, _ in per})
    print(f"{'model':<28}" + "".join(f"{lv:>11}" for lv in levels))
    for m in models:
        cells = []
        for lv in levels:
            scen = {sid: majority_label(per[(m, lv, sid)])
                    for (mm, ll, sid) in per if mm == m and ll == lv}
            if scen:
                ok = sum(1 for l in scen.values() if l in ("exact", "category"))
                cells.append(f"{100*ok/len(scen):>9.0f}%")
            else:
                cells.append(f"{'-':>10}")
        print(f"{m:<28}" + "".join(cells))


def rq4(graded):
    print("\n" + "=" * 72)
    print("RQ4 -- cost/latency per correct diagnosis (full level)")
    print("=" * 72)
    agg = defaultdict(lambda: {"tok": 0, "lat": [], "correct": 0, "n": 0})
    for r in graded:
        if r.get("level") != "full" or "parsed" not in r:
            continue
        a = agg[r["model"]]
        a["n"] += 1
        a["lat"].append(r.get("latency_s", 0))
        u = r.get("usage") or {}
        a["tok"] += u.get("total_tokens", 0)
        if r["grade"]["label"] in ("exact", "category"):
            a["correct"] += 1
    print(f"{'model':<28}{'med lat s':>10}{'tot tok':>10}{'tok/correct':>13}{'correct%':>10}")
    for m, a in sorted(agg.items()):
        med = st.median(a["lat"]) if a["lat"] else 0
        tpc = a["tok"] / a["correct"] if a["correct"] else float("nan")
        print(f"{m:<28}{med:>10.2f}{a['tok']:>10}{tpc:>13.0f}"
              f"{100*a['correct']/max(a['n'],1):>9.0f}%")


def main():
    rows = load()
    if not rows:
        print("no results yet in", RESULTS)
        return
    graded = graded_rows(rows)
    print(f"loaded {len(rows)} answers, graded {len(graded)}\n")
    msl = rq1(graded)
    rq1_by_category(graded, msl)
    rq2(graded)
    rq4(graded)


if __name__ == "__main__":
    main()
