"""Paper 5 RQ1: managed-cluster provisioning + deletion latency trials.

Per trial: t0 = CLI create invoked -> t_cli (create command returns) ->
t_api (API server /readyz via kubectl) -> t_nodes (all nodes Ready);
then timed delete. Client-observed monotonic clock. Appends provision_<cloud>.csv.

Shapes: smallest practical 2-node pool per cloud (documented per-cloud; exact
parity impossible across clouds and stated so in the paper).
EKS note: eksctl provisions a dedicated VPC per cluster (that IS the EKS
experience; decomposition noted). OKE note: VCN/subnets pre-created once and
reused; cluster+nodepool timed (network setup reported separately once).

Usage: python provision_trials.py --cloud aks|eks|gke|oke --trials 5
"""

import argparse
import csv
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

GCLOUD = os.path.expandvars(r"%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd")
EKSCTL = (r"C:\Users\Admin\AppData\Local\Temp\claude\C--Users-Admin-Downloads-EB1A"
          r"\c8ba4e05-ab09-4064-9c1a-28ee8604cd44\scratchpad\eksctl.exe")
HERE = Path(__file__).parent


def sh(cmd, timeout=3600, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          env=e, shell=isinstance(cmd, str))


def wait_api(ctx, deadline_s=1800):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < deadline_s:
        r = sh(["kubectl", "--context", ctx, "get", "--raw", "/readyz",
                "--request-timeout=5s"], timeout=30)
        if r.returncode == 0:
            return time.perf_counter()
        time.sleep(5)
    return None


def wait_nodes(ctx, want, deadline_s=1800):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < deadline_s:
        r = sh(["kubectl", "--context", ctx, "get", "nodes", "--no-headers"],
               timeout=30)
        if r.returncode == 0:
            lines = [l for l in r.stdout.splitlines() if l.strip()]
            if len(lines) >= want and all(" Ready" in l or l.split()[1] == "Ready"
                                          for l in lines):
                return time.perf_counter()
        time.sleep(10)
    return None


class AKS:
    ctx = "p5-aks"
    rg = "p5-ops"
    region = "eastus"

    def pre(self):
        sh(["az", "group", "create", "-n", self.rg, "-l", self.region], timeout=300)

    def create(self, name):
        r = sh(["az", "aks", "create", "-g", self.rg, "-n", name,
                "--node-count", "2", "--node-vm-size", "Standard_B2s",
                "--generate-ssh-keys"], timeout=3600)
        return r.returncode == 0, r.stderr[-300:]

    def kubeconfig(self, name):
        sh(["az", "aks", "get-credentials", "-g", self.rg, "-n", name,
            "--context", self.ctx, "--overwrite-existing"], timeout=300)

    def delete(self, name):
        r = sh(["az", "aks", "delete", "-g", self.rg, "-n", name, "--yes"],
               timeout=3600)
        return r.returncode == 0

    def post(self):
        pass  # rg deleted at campaign end by teardown


class EKS:
    ctx = "p5-eks"
    region = "us-east-1"

    def pre(self):
        pass

    def create(self, name):
        r = sh([EKSCTL, "create", "cluster", "--name", name, "--region",
                self.region, "--nodes", "2", "--node-type", "t3.micro",
                "--managed"], timeout=3600,
               env={"AWS_PROFILE": "drnew"})
        return r.returncode == 0, r.stderr[-300:]

    def kubeconfig(self, name):
        sh(["aws", "eks", "update-kubeconfig", "--name", name, "--region",
            self.region, "--alias", self.ctx], timeout=300,
           env={"AWS_PROFILE": "drnew"})

    def delete(self, name):
        r = sh([EKSCTL, "delete", "cluster", "--name", name, "--region",
                self.region, "--wait"], timeout=3600,
               env={"AWS_PROFILE": "drnew"})
        return r.returncode == 0

    def post(self):
        pass


class GKE:
    ctx_prefix = "gke"
    region = "us-central1-a"  # zonal: cheapest, fastest

    def pre(self):
        sh([GCLOUD, "services", "enable", "container.googleapis.com"],
           timeout=600)

    def create(self, name):
        r = sh([GCLOUD, "container", "clusters", "create", name,
                "--zone", self.region, "--num-nodes", "2",
                "--machine-type", "e2-small", "--quiet"], timeout=3600)
        return r.returncode == 0, r.stderr[-300:]

    def kubeconfig(self, name):
        sh([GCLOUD, "container", "clusters", "get-credentials", name,
            "--zone", self.region], timeout=300)
        # context name: gke_<project>_<zone>_<name); rename for harness
        r = sh(["kubectl", "config", "get-contexts", "-o", "name"], timeout=30)
        for c in r.stdout.splitlines():
            if c.endswith("_" + name):
                sh(["kubectl", "config", "rename-context", c, self.ctx], timeout=30)
        return None

    ctx = "p5-gke"

    def delete(self, name):
        r = sh([GCLOUD, "container", "clusters", "delete", name,
                "--zone", self.region, "--quiet"], timeout=3600)
        return r.returncode == 0

    def post(self):
        pass


CLOUDS = {"aks": AKS, "eks": EKS, "gke": GKE}


def trial(cloud, impl, n, out):
    name = f"p5-{cloud}-t{n}"
    print(f"[{time.strftime('%H:%M:%S')}] {cloud} trial {n}: create {name}",
          flush=True)
    t0 = time.perf_counter()
    ok, err = impl.create(name)
    t_cli = time.perf_counter()
    if not ok:
        write(out, {"cloud": cloud, "trial": n, "create_cli_s": "FAILED",
                    "api_s": err, "nodes_s": "", "delete_s": "",
                    "wallclock": datetime.now(timezone.utc).isoformat()})
        return
    impl.kubeconfig(name)
    t_api = wait_api(impl.ctx)
    t_nodes = wait_nodes(impl.ctx, 2)
    td0 = time.perf_counter()
    impl.delete(name)
    td1 = time.perf_counter()
    sh(["kubectl", "config", "delete-context", impl.ctx], timeout=30)
    write(out, {
        "cloud": cloud, "trial": n,
        "create_cli_s": round(t_cli - t0, 1),
        "api_s": round(t_api - t0, 1) if t_api else "TIMEOUT",
        "nodes_s": round(t_nodes - t0, 1) if t_nodes else "TIMEOUT",
        "delete_s": round(td1 - td0, 1),
        "wallclock": datetime.now(timezone.utc).isoformat(),
    })
    print(f"[{time.strftime('%H:%M:%S')}] {cloud} trial {n}: "
          f"cli={round(t_cli - t0,1)} nodes={round((t_nodes or 0) - t0,1)} "
          f"delete={round(td1 - td0,1)}", flush=True)


def write(out, row):
    exists = Path(out).exists()
    with open(out, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["cloud", "trial", "create_cli_s",
                                          "api_s", "nodes_s", "delete_s",
                                          "wallclock"])
        if not exists:
            w.writeheader()
        w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", required=True, choices=list(CLOUDS))
    ap.add_argument("--trials", type=int, default=5)
    args = ap.parse_args()
    impl = CLOUDS[args.cloud]()
    out = HERE / f"provision_{args.cloud}.csv"
    impl.pre()
    for n in range(1, args.trials + 1):
        trial(args.cloud, impl, n, out)
    print("campaign done", flush=True)


if __name__ == "__main__":
    main()
