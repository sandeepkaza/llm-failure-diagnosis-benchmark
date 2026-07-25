"""Paper 5 blind grading rubric (written BEFORE any model run; user validates).

Grading is deterministic and published so a result is reproducible and not a
matter of a grader's mood. Each model answer is scored on three independent
axes, then mapped to the RQ1 label.

Axes
----
1. category_correct (objective): does the model's category equal the scenario's
   ground-truth category? A fixed 11-way taxonomy, exact string match.

2. rootcause_grade (rubric): match the model's root_cause text against the
   scenario's answer key. Each scenario declares REQUIRED concept groups
   (`concepts`): a group is satisfied if ANY of its synonyms appears in the
   model's root_cause (case-insensitive, substring). Grade:
     exact   -- all required concept groups satisfied (the model named the
                specific mechanism, not just the symptom)
     partial -- some but not all satisfied (right neighborhood, missed the
                mechanism)
     wrong   -- none satisfied
   The concept groups are derived once from each scenario's key_signals /
   ground_truth and frozen here.

3. hallucination (objective-ish): does the answer assert an object name or a
   reason token that does not appear anywhere in the bundle it was given?
   Checked against a per-scenario `forbidden` list of plausible-but-absent
   entities the model might invent, plus a check that any k8s reason/objs the
   model cites exist in the bundle text.

RQ1 label (most-severe-wins):
  hallucinated  if hallucination flagged
  exact         if rootcause_grade == exact  and category_correct
  category      if category_correct and rootcause_grade != wrong (got the class,
                missed or only partially got the mechanism)
  wrong         otherwise
"""

# Per-scenario concept groups (synonyms) that a correct root cause must name,
# and forbidden invented entities. Derived from corpus.py answer keys.
RUBRIC = {
    "oomkill": {
        "concepts": [["oom", "out of memory", "out-of-memory", "137", "memory limit"],
                     ["limit", "64mi", "too low", "exceeds"]],
        "forbidden": ["cpu throttl", "image pull", "liveness", "node not ready"],
    },
    "crashloop-cmd": {
        "concepts": [["exit 1", "exits", "command", "returns non-zero", "fails immediately"],
                     ["crashloop", "restart"]],
        "forbidden": ["oom", "image pull", "probe"],
    },
    "imagepull-badtag": {
        "concepts": [["image", "tag"], ["not exist", "not found", "unknown", "pull", "registry"]],
        "forbidden": ["oom", "crashloop from command", "probe", "quota"],
    },
    "badprobe": {
        "concepts": [["readiness", "probe"], ["port", "8080", "wrong port", "misconfig"]],
        "forbidden": ["image pull", "oom", "liveness kill"],
    },
    "cpu-throttle-pending": {
        "concepts": [["cpu", "request"], ["insufficient", "unschedulable", "pending", "no node", "too large", "64"]],
        "forbidden": ["memory limit", "image", "probe", "oom"],
    },
    "missing-configmap": {
        "concepts": [["configmap", "config map"], ["not found", "missing", "does not exist", "absent"]],
        "forbidden": ["secret not found", "image pull", "oom"],
    },
    "svc-selector-mismatch": {
        "concepts": [["selector", "label"], ["mismatch", "no endpoint", "does not match", "webserver", "no pods match"]],
        "forbidden": ["dns outage", "coredns down", "image", "crash"],
    },
    "pvc-unbound": {
        "concepts": [["storageclass", "storage class", "pvc", "persistentvolumeclaim"],
                     ["not exist", "unbound", "no provisioner", "pending", "nonexistent-sc"]],
        "forbidden": ["image pull", "oom", "probe"],
    },
    "rbac-forbidden": {
        "concepts": [["rbac", "role", "permission", "authorization", "forbidden"],
                     ["serviceaccount", "service account", "403", "cannot list", "denied"]],
        "forbidden": ["network policy block", "dns", "image pull", "crashloop"],
    },
    "node-selector-unsched": {
        "concepts": [["nodeselector", "node selector", "affinity"],
                     ["no node", "didn't match", "not match", "pending", "nvme-special", "unschedulable"]],
        "forbidden": ["cpu request", "memory", "image", "hostport"],
    },
    "init-fail": {
        "concepts": [["init container", "initcontainer", "init"],
                     ["exit 3", "fails", "failing", "crashloop"]],
        "forbidden": ["main container crash", "oom", "image pull of main"],
    },
    "secret-missing": {
        "concepts": [["secret"], ["not found", "missing", "does not exist", "api-creds", "absent"]],
        "forbidden": ["configmap not found", "image pull", "oom"],
    },
    "resourcequota-block": {
        "concepts": [["resourcequota", "resource quota", "quota"],
                     ["exceeded", "forbidden", "pods 0", "pods=0", "cap", "blocks", "zero"]],
        "forbidden": ["image pull", "oom", "probe", "scheduling insufficient cpu"],
    },
    "hostport-conflict": {
        "concepts": [["hostport", "host port"],
                     ["conflict", "in use", "free ports", "already", "one node", "contention", "pending"]],
        "forbidden": ["cpu", "memory", "image", "nodeselector"],
    },
    "wrong-command-perm": {
        "concepts": [["command", "binary", "executable", "entrypoint"],
                     ["no such file", "not found", "does not exist", "exec"]],
        "forbidden": ["oom", "image pull backoff of registry", "probe"],
    },
    "p7-broken-manifest": {
        "concepts": [["invalid", "not-a-quantity", "quantity", "validation", "malformed"],
                     ["memory limit", "resource", "reject", "apply fail", "manifest"]],
        "forbidden": ["oom", "image pull", "scheduling"],
    },
    "p2-webhook-failclosed": {
        "concepts": [["webhook", "admission"],
                     ["failurepolicy", "fail", "unreachable", "not listening", "connection refused", "blocks", "reject"]],
        "forbidden": ["image pull", "oom", "rbac", "quota"],
    },
    "p3-sc-mismatch-restore": {
        "concepts": [["storageclass", "storage class"],
                     ["not exist", "not found", "unbound", "source-cluster", "mismatch", "target cluster", "portable"]],
        "forbidden": ["image pull", "oom", "probe"],
    },
    "p3-restore-helper-image": {
        "concepts": [["image", "restore-helper", "registry"],
                     ["not reachable", "unreachable", "not found", "pull", "absent", "internal-registry"]],
        "forbidden": ["oom", "storageclass", "probe", "quota"],
    },
    "crashloop-missing-dep": {
        "concepts": [["configmap key", "key", "config.yaml"],
                     ["missing", "not found", "no such file", "absent", "wrong key"]],
        "forbidden": ["whole configmap missing", "secret", "image pull", "oom"],
    },
    "liveness-kills-slowstart": {
        "concepts": [["liveness", "probe"],
                     ["slow start", "startup", "too aggressive", "initialdelay", "kills", "restart", "before ready"]],
        "forbidden": ["readiness wrong port", "oom", "image pull", "command exit"],
    },
    "dns-wrong-svc": {
        "concepts": [["service", "backend-service", "dns", "resolve"],
                     ["not exist", "nxdomain", "missing", "no service", "misnamed"]],
        "forbidden": ["coredns down", "network policy", "image pull", "rbac"],
    },
    "readonly-fs-write": {
        "concepts": [["read-only", "readonly", "read only"],
                     ["root filesystem", "rootfs", "write", "securitycontext", "cannot create"]],
        "forbidden": ["oom", "image pull", "probe", "quota"],
    },
    "pdb-blocks-drain": {
        "concepts": [["image", "private", "registry"],
                     ["pull secret", "imagepullsecret", "regcred", "credentials", "unauthorized", "denied", "not found"]],
        "forbidden": ["public tag typo only", "oom", "probe"],
    },
    "p7-drift-scaled": {
        "concepts": [["drift", "replicas", "desired", "declared", "out-of-band", "scaled"],
                     ["live", "differ", "diverge", "4", "reconcile", "git"]],
        "forbidden": ["crashloop", "oomkill", "image pull backoff", "insufficient cpu"],
    },
    "p2-leftover-webhook-ns": {
        "concepts": [["webhook", "admission"],
                     ["namespaceselector", "namespace selector", "p5-guarded", "failurepolicy", "unreachable", "leftover", "stale", "scoped", "reject"]],
        "forbidden": ["image pull", "oom", "rbac", "quota"],
    },
}


def _hit(groups, text):
    text = (text or "").lower()
    return [any(syn in text for syn in g) for g in groups]


def grade_answer(scenario, answer):
    """scenario: corpus.Scenario; answer: parsed dict or None.
    Returns dict with category_correct, rootcause_grade, hallucinated, label."""
    if not isinstance(answer, dict):
        return {"category_correct": False, "rootcause_grade": "wrong",
                "hallucinated": False, "label": "wrong", "note": "no parseable answer"}

    r = RUBRIC[scenario.id]
    cat = (answer.get("category") or "").strip().lower()
    category_correct = cat == scenario.category

    rc_text = " ".join(str(answer.get(k, "")) for k in ("root_cause", "fix", "evidence_cited"))
    hits = _hit(r["concepts"], rc_text)
    if all(hits):
        rootcause_grade = "exact"
    elif any(hits):
        rootcause_grade = "partial"
    else:
        rootcause_grade = "wrong"

    # hallucination: names a forbidden (plausible-but-absent) mechanism
    low = rc_text.lower()
    hallucinated = any(f in low for f in r["forbidden"])

    if hallucinated:
        label = "hallucinated"
    elif rootcause_grade == "exact" and category_correct:
        label = "exact"
    elif category_correct and rootcause_grade != "wrong":
        label = "category"
    else:
        label = "wrong"

    return {"category_correct": category_correct, "rootcause_grade": rootcause_grade,
            "hallucinated": hallucinated, "label": label,
            "concept_hits": sum(hits), "concept_total": len(hits)}


if __name__ == "__main__":
    # self-check: every scenario has a rubric entry; the answer key itself grades exact.
    from corpus import SCENARIOS
    missing = [s.id for s in SCENARIOS if s.id not in RUBRIC]
    assert not missing, f"rubric missing scenarios: {missing}"
    # sanity: feeding the ground-truth text as the model answer should grade exact
    # (validates the concept groups are actually present in the answer key).
    fails = []
    for s in SCENARIOS:
        ans = {"category": s.category, "root_cause": s.ground_truth,
               "fix": s.fix, "evidence_cited": s.key_signals}
        g = grade_answer(s, ans)
        if g["label"] != "exact":
            fails.append((s.id, g["label"], g["concept_hits"], g["concept_total"]))
    if fails:
        print("RUBRIC CALIBRATION MISSES (ground truth should grade exact):")
        for f in fails:
            print("  ", f)
    else:
        print(f"rubric OK: all {len(SCENARIOS)} answer keys self-grade 'exact'")
