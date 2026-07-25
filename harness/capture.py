"""Paper 5 evidence-capture harness.

For each scenario: create a clean namespace, apply its manifests, run any
inject step, wait for the failure to settle, then capture an evidence bundle
that a competent SRE would triage from -- pod status/describe, namespace
events, container logs (current + previous), and the relevant object states --
and tear the namespace down. Bundles are sanitized (cluster-specific names,
IPs, and timestamps normalized) and written as JSON to bundles/<id>.json.

The capture is the citable artifact and is engine/model-agnostic: it runs
once, offline, and the model runs read the static bundles. Ground truth is
NOT written into the bundle (it lives in corpus.py / the rubric).

Usage (on a cluster with kubectl context set):
  python capture.py                 # all scenarios
  python capture.py oomkill badprobe # subset
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from corpus import SCENARIOS, NS, by_id

HERE = Path(__file__).parent
OUT = HERE / "bundles"
OUT.mkdir(exist_ok=True)


def sh(args, timeout=120, input_str=None):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          input=input_str, shell=isinstance(args, str))


def kubectl(*args, timeout=120):
    return sh(["kubectl", *args], timeout=timeout)


def sanitize(text):
    """Normalize volatile tokens so bundles are stable and comparable."""
    if not text:
        return text
    # ISO timestamps -> <TS>; ages like 12s/3m -> <AGE>; ip:port -> <IP>; uids
    text = re.sub(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?", "<TS>", text)
    text = re.sub(r"\b\d+(\.\d+)?(s|m|h|d)\b", "<AGE>", text)
    text = re.sub(r"\b\d{1,3}(\.\d{1,3}){3}\b", "<IP>", text)
    text = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                  "<UID>", text)
    # pod hash suffixes: name-abc12-xy34 -> name-<HASH>
    text = re.sub(r"-[0-9a-f]{6,10}-[a-z0-9]{5}\b", "-<HASH>", text)
    return text


def capture_one(s):
    print(f"[{time.strftime('%H:%M:%S')}] {s.id}: apply", flush=True)
    kubectl("delete", "ns", NS, "--ignore-not-found", "--wait=true", timeout=180)
    kubectl("create", "ns", NS, timeout=60)
    # cluster-scoped objects (webhooks) are cleaned by id prefix
    kubectl("delete", "validatingwebhookconfiguration", "-l", "p5=owned",
            "--ignore-not-found", timeout=60)

    ap = sh(["kubectl", "apply", "-n", NS, "-f", "-"], input_str=s.manifests, timeout=120)
    apply_out = ap.stdout + ap.stderr
    if s.inject:
        sh(s.inject, timeout=120)
    time.sleep(s.settle_s)

    bundle = {
        "scenario_id": s.id,
        "title": s.title,
        "namespace": NS,
        "apply_result": sanitize(apply_out.strip()),
        "evidence": {},
    }
    ev = bundle["evidence"]

    # 1. pods: wide status
    ev["pods"] = sanitize(kubectl("get", "pods", "-n", NS, "-o", "wide").stdout)
    # 2. describe pods (the richest single triage view)
    ev["describe_pods"] = sanitize(kubectl("describe", "pods", "-n", NS).stdout)
    # 3. namespace events, sorted
    ev["events"] = sanitize(kubectl("get", "events", "-n", NS,
                                    "--sort-by=.lastTimestamp").stdout)
    # 4. logs (current + previous) for each pod/container, best effort
    logs = {}
    pods = kubectl("get", "pods", "-n", NS, "-o",
                   "jsonpath={range .items[*]}{.metadata.name}{'\\n'}{end}").stdout.split()
    for p in pods[:8]:
        cur = kubectl("logs", "-n", NS, p, "--all-containers", "--tail=40").stdout
        prev = kubectl("logs", "-n", NS, p, "--all-containers", "--previous",
                       "--tail=40").stdout
        logs[p] = {"current": sanitize(cur.strip()), "previous": sanitize(prev.strip())}
    ev["logs"] = logs
    # 5. workloads + services + pvc + quota (object-level state)
    ev["workloads"] = sanitize(kubectl(
        "get", "deploy,rs,job,svc,pvc,resourcequota,configmap,secret",
        "-n", NS, "-o", "wide").stdout)
    # 6. relevant cluster-scoped: webhooks (for admission scenarios)
    ev["webhooks"] = sanitize(kubectl(
        "get", "validatingwebhookconfiguration,mutatingwebhookconfiguration",
        "-o", "wide").stdout)
    # 7. declared intent: object annotations (the desired-state markers a
    #    GitOps drift is only diagnosable against; -o wide hides these).
    ev["annotations"] = sanitize(kubectl(
        "get", "deploy,statefulset", "-n", NS, "-o",
        "jsonpath={range .items[*]}{.kind}/{.metadata.name} "
        "spec.replicas={.spec.replicas} annotations={.metadata.annotations}"
        "{'\\n'}{end}").stdout)

    (OUT / f"{s.id}.json").write_text(json.dumps(bundle, indent=1), encoding="utf-8")
    print(f"[{time.strftime('%H:%M:%S')}] {s.id}: captured "
          f"({sum(len(str(v)) for v in ev.values())} chars)", flush=True)

    kubectl("delete", "ns", NS, "--ignore-not-found", "--wait=false", timeout=60)
    kubectl("delete", "validatingwebhookconfiguration",
            "p5-deadwebhook", "p5-leftover-nswebhook", "--ignore-not-found", timeout=60)


def main():
    which = sys.argv[1:]
    scen = [by_id(x) for x in which] if which else SCENARIOS
    for s in scen:
        try:
            capture_one(s)
        except Exception as e:
            print(f"!! {s.id} capture error: {e}", flush=True)
    print(f"captured {len(list(OUT.glob('*.json')))} bundles to {OUT}", flush=True)


if __name__ == "__main__":
    main()
