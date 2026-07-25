"""Paper 5 fault corpus: ground-truth cloud-native failure scenarios.

Each scenario is a self-contained, reproducible injected fault with a KNOWN
root cause and a KNOWN correct fix, defined before any model sees it. A
scenario applies manifests to a namespace, optionally runs an inject action,
waits for the failure to manifest, and is then captured (capture.py) into an
evidence bundle. The ground_truth / fix / category fields are the answer key
used by the blind rubric (rubric.py) -- they are never shown to a diagnoser.

Categories (the RQ1 grading taxonomy's coarse buckets):
  scheduling | image | config | probe | resource | storage | network |
  rbac | admission | gitops | crash

Scenarios span three provenances:
  - K8s classics (the failures every operator sees)
  - our own prior-paper findings (P2 admission, P3 DR, P7 GitOps) -- the
    unique ground truth this program owns
Every scenario is designed so the evidence bundle CONTAINS the signal a
competent SRE would need, so a wrong diagnosis is a model failure, not missing
evidence (RQ2 then removes evidence deliberately).
"""

from dataclasses import dataclass, field


@dataclass
class Scenario:
    id: str
    title: str
    category: str
    provenance: str              # classic | p2 | p3 | p7
    manifests: str               # YAML applied to the scenario namespace
    inject: str = ""             # optional shell (kubectl) run after apply
    settle_s: int = 40           # wait before capture
    ground_truth: str = ""       # the root cause (answer key)
    fix: str = ""                # the correct remediation (answer key)
    dangerous_fixes: list = field(default_factory=list)  # fixes that would harm
    key_signals: list = field(default_factory=list)      # evidence a good diagnosis cites


NS = "p5"

SCENARIOS = [
    # ---------------- K8s classics ----------------
    Scenario(
        id="oomkill", title="Container OOMKilled under low memory limit",
        category="resource", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: oomkill, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: oomkill}}
  template:
    metadata: {labels: {app: oomkill}}
    spec:
      containers:
      - name: hog
        image: python:3.11-slim
        command: ["python","-c","b=bytearray(500*1024*1024); import time; time.sleep(600)"]
        resources: {limits: {memory: "64Mi"}, requests: {memory: "64Mi"}}
""",
        ground_truth="The container allocates ~500MB but its memory limit is 64Mi, so the kernel OOM-kills it; it restarts and is OOMKilled again (CrashLoopBackOff with reason OOMKilled, exit 137).",
        fix="Raise the memory limit to exceed the working set (or reduce the app's memory use).",
        dangerous_fixes=["Remove the memory limit entirely on a shared node (lets one pod exhaust node memory)."],
        key_signals=["lastState.terminated.reason=OOMKilled", "exit code 137", "restartCount rising"],
    ),
    Scenario(
        id="crashloop-cmd", title="CrashLoopBackOff from a failing command",
        category="crash", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: crashloop, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: crashloop}}
  template:
    metadata: {labels: {app: crashloop}}
    spec:
      containers:
      - name: c
        image: busybox:1.36
        command: ["sh","-c","echo starting; exit 1"]
""",
        ground_truth="The container's command exits 1 immediately on every start, so Kubernetes restarts it with exponential backoff (CrashLoopBackOff). The application/command itself is failing, not the platform.",
        fix="Fix the command or the application so it runs successfully and stays up.",
        key_signals=["reason=CrashLoopBackOff", "exit code 1", "container logs show the failure"],
    ),
    Scenario(
        id="imagepull-badtag", title="ImagePullBackOff from a nonexistent tag",
        category="image", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: badimage, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: badimage}}
  template:
    metadata: {labels: {app: badimage}}
    spec:
      containers:
      - name: c
        image: nginx:this-tag-does-not-exist-9x9
""",
        ground_truth="The referenced image tag does not exist in the registry, so the kubelet cannot pull it (ErrImagePull -> ImagePullBackOff). The pod never starts.",
        fix="Correct the image tag to one that exists in the registry.",
        key_signals=["reason=ImagePullBackOff / ErrImagePull", "Failed to pull image event", "manifest unknown / not found"],
    ),
    Scenario(
        id="badprobe", title="Readiness probe never passes (wrong port)",
        category="probe", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: badprobe, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: badprobe}}
  template:
    metadata: {labels: {app: badprobe}}
    spec:
      containers:
      - name: c
        image: nginx:1.27
        ports: [{containerPort: 80}]
        readinessProbe:
          httpGet: {path: /, port: 8080}
          periodSeconds: 5
""",
        ground_truth="nginx listens on port 80 but the readiness probe checks port 8080, so the probe always fails; the pod runs but never becomes Ready and is kept out of Service endpoints. The container is healthy; the probe is misconfigured.",
        fix="Point the readiness probe at port 80 (the port the container actually serves).",
        dangerous_fixes=["Delete the readiness probe (masks real readiness failures in future)."],
        key_signals=["Readiness probe failed: connection refused", "pod Running but 0/1 Ready", "container itself has no errors"],
    ),
    Scenario(
        id="cpu-throttle-pending", title="Pod Pending: unschedulable CPU request",
        category="scheduling", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: toobig, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: toobig}}
  template:
    metadata: {labels: {app: toobig}}
    spec:
      containers:
      - name: c
        image: nginx:1.27
        resources: {requests: {cpu: "64"}}
""",
        ground_truth="The pod requests 64 CPUs, more than any node offers, so the scheduler cannot place it and it stays Pending with FailedScheduling (Insufficient cpu). It is a resource-request problem, not a crash.",
        fix="Lower the CPU request to fit an available node (or add a larger node).",
        key_signals=["status=Pending", "FailedScheduling: Insufficient cpu", "no events on the container (never scheduled)"],
    ),
    Scenario(
        id="missing-configmap", title="Pod stuck: referenced ConfigMap absent",
        category="config", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: needsconfig, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: needsconfig}}
  template:
    metadata: {labels: {app: needsconfig}}
    spec:
      containers:
      - name: c
        image: nginx:1.27
        envFrom: [{configMapRef: {name: app-config}}]
""",
        ground_truth="The pod references a ConfigMap 'app-config' via envFrom, but that ConfigMap does not exist, so the kubelet cannot create the container (CreateContainerConfigError). The workload is fine; a dependency is missing.",
        fix="Create the missing 'app-config' ConfigMap (or remove the envFrom reference).",
        key_signals=["reason=CreateContainerConfigError", "configmap \"app-config\" not found", "pod not starting"],
    ),
    Scenario(
        id="svc-selector-mismatch", title="Service has no endpoints (selector mismatch)",
        category="network", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: web}}
  template:
    metadata: {labels: {app: web}}
    spec:
      containers: [{name: c, image: nginx:1.27, ports: [{containerPort: 80}]}]
---
apiVersion: v1
kind: Service
metadata: {name: web, namespace: p5}
spec:
  selector: {app: webserver}
  ports: [{port: 80, targetPort: 80}]
""",
        ground_truth="The Service selector is app=webserver but the pods are labeled app=web, so the Service matches no pods and has zero endpoints; traffic to the Service fails though the pods are healthy. A label/selector mismatch, not a pod failure.",
        fix="Align the Service selector (app=web) with the pod labels.",
        key_signals=["Service endpoints empty", "pods Running and Ready", "selector != pod labels"],
    ),
    Scenario(
        id="pvc-unbound", title="Pod Pending: PVC unbound (no matching StorageClass)",
        category="storage", provenance="classic",
        manifests="""
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: data, namespace: p5}
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: nonexistent-sc
  resources: {requests: {storage: 1Gi}}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: needsdisk, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: needsdisk}}
  template:
    metadata: {labels: {app: needsdisk}}
    spec:
      containers: [{name: c, image: nginx:1.27, volumeMounts: [{name: d, mountPath: /data}]}]
      volumes: [{name: d, persistentVolumeClaim: {claimName: data}}]
""",
        ground_truth="The PVC requests StorageClass 'nonexistent-sc' which has no provisioner, so the PVC stays Pending (unbound) and the pod cannot mount the volume, keeping the pod Pending. A storage-class misconfiguration.",
        fix="Use an existing StorageClass (or create the named one with a valid provisioner).",
        key_signals=["PVC status=Pending", "pod Pending: unbound PersistentVolumeClaim", "storageclass not found"],
    ),
    Scenario(
        id="rbac-forbidden", title="App gets 403 Forbidden from the API (missing RBAC)",
        category="rbac", provenance="classic",
        manifests="""
apiVersion: v1
kind: ServiceAccount
metadata: {name: lister, namespace: p5}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: apilister, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: apilister}}
  template:
    metadata: {labels: {app: apilister}}
    spec:
      serviceAccountName: lister
      containers:
      - name: c
        image: curlimages/curl:8.10.1
        command:
        - sh
        - -c
        - |
          T=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
          while true; do
            echo "--- listing pods via API ---"
            curl -s -k -H "Authorization: Bearer $T" https://kubernetes.default.svc/api/v1/namespaces/p5/pods
            echo
            sleep 8
          done
""",
        ground_truth="The pod's ServiceAccount 'lister' has no RBAC role granting list on pods, so its API calls return 403 Forbidden. The container runs; its API access is denied by authorization, not a network or crash fault.",
        fix="Bind a Role/ClusterRole granting get/list on pods to the 'lister' ServiceAccount.",
        key_signals=["logs: Error from server (Forbidden)", "cannot list resource \"pods\"", "container Running, no restarts"],
    ),
    Scenario(
        id="node-selector-unsched", title="Pod Pending: nodeSelector matches no node",
        category="scheduling", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: picky, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: picky}}
  template:
    metadata: {labels: {app: picky}}
    spec:
      nodeSelector: {disktype: nvme-special}
      containers: [{name: c, image: nginx:1.27}]
""",
        ground_truth="The pod's nodeSelector requires a node labeled disktype=nvme-special, which no node has, so the scheduler cannot place it (FailedScheduling: node(s) didn't match node selector). A scheduling-constraint problem.",
        fix="Remove the nodeSelector or label a node with disktype=nvme-special.",
        key_signals=["FailedScheduling", "didn't match Pod's node affinity/selector", "Pending"],
    ),
    Scenario(
        id="init-fail", title="Pod stuck Init: init container fails",
        category="crash", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: initfail, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: initfail}}
  template:
    metadata: {labels: {app: initfail}}
    spec:
      initContainers:
      - name: setup
        image: busybox:1.36
        command: ["sh","-c","echo preparing; exit 3"]
      containers: [{name: c, image: nginx:1.27}]
""",
        ground_truth="The init container 'setup' exits 3, so the pod never progresses past Init (Init:CrashLoopBackOff) and the main container never starts. The failure is in the init step, not the app.",
        fix="Fix the init container's command so it succeeds (exit 0).",
        key_signals=["status=Init:CrashLoopBackOff", "init container setup terminated exit 3", "main container never started"],
    ),
    Scenario(
        id="secret-missing", title="Pod cannot start: referenced Secret absent",
        category="config", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: needssecret, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: needssecret}}
  template:
    metadata: {labels: {app: needssecret}}
    spec:
      containers:
      - name: c
        image: nginx:1.27
        env:
        - name: TOKEN
          valueFrom: {secretKeyRef: {name: api-creds, key: token}}
""",
        ground_truth="The pod reads env TOKEN from Secret 'api-creds', which does not exist, so the container cannot be created (CreateContainerConfigError: secret not found). A missing-dependency (secret) fault.",
        fix="Create the 'api-creds' Secret with a 'token' key (or remove the env reference).",
        key_signals=["reason=CreateContainerConfigError", "secret \"api-creds\" not found", "not starting"],
    ),
    Scenario(
        id="resourcequota-block", title="Deployment makes no pods (ResourceQuota blocks)",
        category="resource", provenance="classic",
        manifests="""
apiVersion: v1
kind: ResourceQuota
metadata: {name: tight, namespace: p5}
spec:
  hard: {pods: "0"}
""",
        inject="kubectl -n p5 create deployment quotablocked --image=nginx:1.27 --replicas=1 || true",
        ground_truth="A ResourceQuota in the namespace caps pods at 0, so the ReplicaSet cannot create any pod; the Deployment reports 0 available and events show 'forbidden: exceeded quota'. The controller is blocked by admission-time quota, not a pod failure.",
        fix="Raise or remove the ResourceQuota pod cap so the namespace can create pods.",
        dangerous_fixes=["Delete all ResourceQuotas cluster-wide (removes guardrails on every namespace)."],
        key_signals=["ReplicaSet events: forbidden: exceeded quota", "0 pods created", "quota pods=0"],
    ),
    Scenario(
        id="hostport-conflict", title="Second pod Pending: hostPort already in use",
        category="scheduling", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: hostport, namespace: p5}
spec:
  replicas: 2
  selector: {matchLabels: {app: hostport}}
  template:
    metadata: {labels: {app: hostport}}
    spec:
      containers:
      - name: c
        image: nginx:1.27
        ports: [{containerPort: 80, hostPort: 30099}]
""",
        ground_truth="Both replicas request hostPort 30099 on a single-node cluster; only one can bind it, so the second stays Pending (FailedScheduling: node(s) didn't have free ports). A hostPort contention problem on scheduling.",
        fix="Remove hostPort (use a Service/NodePort) or run one replica per node.",
        key_signals=["one pod Running, one Pending", "didn't have free ports for the requested pod ports", "hostPort 30099"],
    ),
    Scenario(
        id="wrong-command-perm", title="CrashLoop: command not executable / not found",
        category="crash", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: nocmd, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: nocmd}}
  template:
    metadata: {labels: {app: nocmd}}
    spec:
      containers:
      - name: c
        image: busybox:1.36
        command: ["/usr/local/bin/does-not-exist"]
""",
        ground_truth="The container's command points at a binary that does not exist in the image, so container creation fails with 'exec: no such file or directory' (StartError / RunContainerError), looping. An image/command mismatch, not a resource fault.",
        fix="Set the command to a path that exists in the image.",
        key_signals=["exec: \"/usr/local/bin/does-not-exist\": stat ... no such file", "RunContainerError/StartError", "restarts"],
    ),

    # ---------------- our own prior-paper findings ----------------
    Scenario(
        id="p7-broken-manifest", title="GitOps: invalid manifest field rejected on apply",
        category="config", provenance="p7",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: gitopsbad, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: gitopsbad}}
  template:
    metadata: {labels: {app: gitopsbad}}
    spec:
      containers:
      - name: c
        image: nginx:1.27
        resources: {limits: {memory: "not-a-quantity"}}
""",
        settle_s=15,
        ground_truth="The manifest sets a memory limit to 'not-a-quantity', an invalid resource quantity, so the API server rejects the object on apply (validation error); in a GitOps flow the sync fails and the desired change never lands. A manifest-validity problem, mirroring Paper 7's broken-manifest failure class.",
        fix="Correct the memory limit to a valid quantity (e.g. 128Mi).",
        key_signals=["apply/validation error: quantities must match", "object not created", "sync/apply fails"],
    ),
    Scenario(
        id="p2-webhook-failclosed", title="Admission: webhook unreachable blocks all creates",
        category="admission", provenance="p2",
        manifests="""
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata: {name: p5-deadwebhook}
webhooks:
- name: dead.p5.example.com
  admissionReviewVersions: ["v1"]
  sideEffects: None
  failurePolicy: Fail
  clientConfig:
    url: "https://127.0.0.1:19999/validate"
  rules:
  - apiGroups: ["apps"]
    apiVersions: ["v1"]
    operations: ["CREATE"]
    resources: ["deployments"]
    scope: "Namespaced"
""",
        inject="kubectl -n p5 create deployment blocked-by-webhook --image=nginx:1.27 || true",
        settle_s=10,
        ground_truth="A ValidatingWebhookConfiguration with failurePolicy=Fail points at an endpoint that is not listening; every Deployment CREATE calls the webhook, the call fails, and because the policy is Fail the API server rejects the request. All deployment creation in scope is blocked by a dead admission webhook -- Paper 2's fail-closed / leftover-webhook failure class.",
        fix="Remove or repair the webhook (fix the endpoint, or set failurePolicy=Ignore for a non-critical hook, or delete the stale configuration).",
        dangerous_fixes=["Set all webhooks to failurePolicy=Ignore globally (silently disables real policy enforcement)."],
        key_signals=["error calling webhook dead.p5.example.com", "failurePolicy Fail", "connection refused to webhook endpoint", "CREATE rejected"],
    ),
    Scenario(
        id="p3-sc-mismatch-restore", title="DR: restored PVC references a StorageClass absent on target",
        category="storage", provenance="p3",
        manifests="""
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: restored-data, namespace: p5}
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: source-cluster-fast-ssd
  resources: {requests: {storage: 2Gi}}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: restored-app, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: restored-app}}
  template:
    metadata: {labels: {app: restored-app}}
    spec:
      containers: [{name: c, image: nginx:1.27, volumeMounts: [{name: d, mountPath: /data}]}]
      volumes: [{name: d, persistentVolumeClaim: {claimName: restored-data}}]
""",
        ground_truth="A PVC restored from another cluster names StorageClass 'source-cluster-fast-ssd', which does not exist on this target cluster, so the PVC stays unbound and the restored app cannot start. This is Paper 3's cross-cluster StorageClass-mismatch DR failure: the backup is valid but the storage class name is not portable across clusters.",
        fix="Remap the PVC to a StorageClass that exists on the target cluster (or pre-create the named class) before/at restore time.",
        key_signals=["PVC Pending unbound", "storageclass source-cluster-fast-ssd not found", "restored app Pending", "cross-cluster restore context"],
    ),
    Scenario(
        id="p3-restore-helper-image", title="DR: restore hook pod uses an image tag absent on target",
        category="image", provenance="p3",
        manifests="""
apiVersion: batch/v1
kind: Job
metadata: {name: restore-helper, namespace: p5}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: helper
        image: internal-registry.local/velero-restore-helper:v1.2.3-source
        command: ["sh","-c","echo restoring"]
""",
        settle_s=30,
        ground_truth="The restore-helper Job references an image from an internal registry/tag that is not reachable or present on the target cluster, so the helper pod cannot pull it (ImagePullBackOff) and the restore never completes. Paper 3's restore-helper-image DR failure: a restore that depends on an image the target cannot obtain.",
        fix="Push/mirror the restore-helper image to a registry the target cluster can reach, or reference an image that exists there.",
        key_signals=["ImagePullBackOff on restore-helper", "internal-registry.local unreachable / tag absent", "restore blocked"],
    ),
    Scenario(
        id="crashloop-missing-dep", title="App crashes: config file mounted but empty key",
        category="config", provenance="classic",
        manifests="""
apiVersion: v1
kind: ConfigMap
metadata: {name: appcfg, namespace: p5}
data: {other.txt: "unused"}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: cfgcrash, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: cfgcrash}}
  template:
    metadata: {labels: {app: cfgcrash}}
    spec:
      containers:
      - name: c
        image: busybox:1.36
        command: ["sh","-c","cat /etc/app/config.yaml && sleep 600"]
        volumeMounts: [{name: cfg, mountPath: /etc/app}]
      volumes:
      - name: cfg
        configMap: {name: appcfg, items: [{key: config.yaml, path: config.yaml}]}
""",
        ground_truth="The volume projects ConfigMap key 'config.yaml', but the ConfigMap only has key 'other.txt'; the projected file is absent, so 'cat /etc/app/config.yaml' fails and the container crashes. The ConfigMap exists but the specific key the app needs is missing -- a subtle config fault distinct from a wholly missing ConfigMap.",
        fix="Add the 'config.yaml' key to the ConfigMap (or point the volume item at an existing key).",
        key_signals=["cat: /etc/app/config.yaml: No such file or directory", "ConfigMap present but key missing", "CrashLoop"],
    ),
    Scenario(
        id="liveness-kills-slowstart", title="Liveness probe kills a slow-starting app",
        category="probe", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: slowstart, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: slowstart}}
  template:
    metadata: {labels: {app: slowstart}}
    spec:
      containers:
      - name: c
        image: nginx:1.27
        command: ["sh","-c","sleep 30; nginx -g 'daemon off;'"]
        livenessProbe:
          httpGet: {path: /, port: 80}
          initialDelaySeconds: 2
          periodSeconds: 3
          failureThreshold: 2
""",
        settle_s=50,
        ground_truth="The app takes ~30s to start serving, but the liveness probe begins after 2s and fails it within ~8s, so the kubelet kills and restarts the container before it can finish starting -- a restart loop caused by a too-aggressive liveness probe, not a broken app. A startupProbe or larger initialDelay would fix it.",
        fix="Add a startupProbe (or increase liveness initialDelaySeconds) to allow the slow start before liveness applies.",
        dangerous_fixes=["Remove the liveness probe (loses genuine hang detection)."],
        key_signals=["Liveness probe failed then Killing container", "restarts every ~30s", "app healthy once started"],
    ),
    Scenario(
        id="dns-wrong-svc", title="App errors: connects to a Service name that doesn't exist",
        category="network", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: dnsfail, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: dnsfail}}
  template:
    metadata: {labels: {app: dnsfail}}
    spec:
      containers:
      - name: c
        image: busybox:1.36
        command: ["sh","-c","while true; do nslookup backend-service.p5.svc.cluster.local || echo LOOKUP_FAILED; sleep 8; done"]
""",
        ground_truth="The app resolves 'backend-service.p5.svc.cluster.local', but no Service named 'backend-service' exists in the namespace, so DNS resolution fails (NXDOMAIN). The application is up; its dependency Service is missing or misnamed -- a service-discovery/DNS fault, not a CoreDNS outage.",
        fix="Create the 'backend-service' Service (or correct the hostname the app uses).",
        key_signals=["nslookup: can't resolve backend-service", "NXDOMAIN", "no Service by that name", "CoreDNS itself healthy"],
    ),
    Scenario(
        id="readonly-fs-write", title="CrashLoop: app writes to a read-only root filesystem",
        category="config", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: rofs, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: rofs}}
  template:
    metadata: {labels: {app: rofs}}
    spec:
      containers:
      - name: c
        image: busybox:1.36
        command: ["sh","-c","echo data > /var/lib/app.state && sleep 600"]
        securityContext: {readOnlyRootFilesystem: true}
""",
        ground_truth="The container's securityContext sets readOnlyRootFilesystem=true, but the app writes to /var/lib/app.state on the root FS, so the write fails ('Read-only file system') and the container crashes. A security-hardening setting incompatible with the app's need to write; the fix is a writable volume, not removing the hardening.",
        fix="Mount an emptyDir (or PVC) at the write path so the app writes there while the root FS stays read-only.",
        dangerous_fixes=["Set readOnlyRootFilesystem=false to 'fix' it (removes a hardening control instead of scoping a writable path)."],
        key_signals=["sh: can't create /var/lib/app.state: Read-only file system", "readOnlyRootFilesystem true", "CrashLoop"],
    ),
    Scenario(
        id="pdb-blocks-drain", title="ReplicaSet degraded: image pull secret missing (private registry)",
        category="image", provenance="classic",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata: {name: privreg, namespace: p5}
spec:
  replicas: 1
  selector: {matchLabels: {app: privreg}}
  template:
    metadata: {labels: {app: privreg}}
    spec:
      imagePullSecrets: [{name: regcred}]
      containers:
      - name: c
        image: ghcr.io/nonexistent-org/private-xyz:1.0
""",
        ground_truth="The deployment references a private image and an imagePullSecret 'regcred' that does not exist; without valid credentials the pull is unauthorized/not-found, so the pod is stuck ImagePullBackOff. The root cause is the missing/invalid pull secret (auth), distinct from a merely wrong public tag.",
        fix="Create the 'regcred' pull secret with valid registry credentials (or reference an accessible image).",
        key_signals=["ImagePullBackOff", "pull access denied / not found", "imagePullSecret regcred missing"],
    ),
    Scenario(
        id="p7-drift-scaled", title="GitOps drift: replicas changed out-of-band from desired",
        category="gitops", provenance="p7",
        manifests="""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: driftapp
  namespace: p5
  annotations: {p5.desired/replicas: "1"}
spec:
  replicas: 1
  selector: {matchLabels: {app: driftapp}}
  template:
    metadata: {labels: {app: driftapp}}
    spec:
      containers: [{name: c, image: nginx:1.27}]
""",
        inject="kubectl -n p5 scale deployment driftapp --replicas=4 || true",
        settle_s=20,
        ground_truth="The Deployment's desired replicas (recorded in git/annotation) is 1, but it was scaled out-of-band to 4; the live state now disagrees with the declared source of truth. Without a reconciler continuously correcting it, the drift persists. This is Paper 7's spec-drift failure class: live state diverged from declared desired state by an out-of-band mutation.",
        fix="Reconcile live state back to the declared desired (scale to 1), and enable/repair the GitOps controller's self-heal so drift is corrected automatically.",
        key_signals=["live replicas=4 vs declared/annotation=1", "no crash or scheduling error", "drift = live != desired"],
    ),
    Scenario(
        id="p2-leftover-webhook-ns", title="Admission: stale namespaceSelector webhook blocks a labeled namespace",
        category="admission", provenance="p2",
        manifests="""
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata: {name: p5-leftover-nswebhook}
webhooks:
- name: leftover.p5.example.com
  admissionReviewVersions: ["v1"]
  sideEffects: None
  failurePolicy: Fail
  namespaceSelector:
    matchLabels: {p5-guarded: "true"}
  clientConfig:
    url: "https://127.0.0.1:19998/validate"
  rules:
  - apiGroups: [""]
    apiVersions: ["v1"]
    operations: ["CREATE"]
    resources: ["configmaps"]
    scope: "Namespaced"
""",
        inject="kubectl label ns p5 p5-guarded=true --overwrite || true; kubectl -n p5 create configmap probe-cm --from-literal=k=v || true",
        settle_s=10,
        ground_truth="A leftover ValidatingWebhookConfiguration with failurePolicy=Fail and a namespaceSelector p5-guarded=true targets a dead endpoint; once the namespace is labeled p5-guarded=true, every ConfigMap CREATE in it is routed to the unreachable webhook and rejected. The blast radius is scoped by the namespaceSelector, so the failure appears only for labeled namespaces -- Paper 2's leftover/stale-webhook class, harder to spot because it is selector-scoped.",
        fix="Delete the stale webhook configuration (or fix its endpoint / relax failurePolicy); the giveaway is that only the labeled namespace is affected.",
        dangerous_fixes=["Remove the p5-guarded label to dodge it (leaves the broken webhook to bite the next labeled namespace)."],
        key_signals=["error calling webhook leftover.p5.example.com", "only affects namespaces labeled p5-guarded=true", "ConfigMap CREATE rejected", "failurePolicy Fail"],
    ),
]


def by_id(sid):
    for s in SCENARIOS:
        if s.id == sid:
            return s
    raise KeyError(sid)


if __name__ == "__main__":
    # self-check: ids unique, every scenario has ground truth + fix + signals,
    # categories in the taxonomy, at least 25 scenarios spanning >=4 provenances.
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids)), "duplicate scenario id"
    cats = {"scheduling", "image", "config", "probe", "resource", "storage",
            "network", "rbac", "admission", "gitops", "crash"}
    for s in SCENARIOS:
        assert s.ground_truth and s.fix and s.key_signals, f"{s.id} missing answer key"
        assert s.category in cats, f"{s.id} bad category {s.category}"
        assert s.manifests.strip(), f"{s.id} empty manifests"
    provs = {s.provenance for s in SCENARIOS}
    assert provs >= {"classic", "p2", "p3", "p7"}, provs
    print(f"corpus OK: {len(SCENARIOS)} scenarios, "
          f"{len({s.category for s in SCENARIOS})} categories, provenances {sorted(provs)}")
    from collections import Counter
    print("by category:", dict(Counter(s.category for s in SCENARIOS)))
    print("by provenance:", dict(Counter(s.provenance for s in SCENARIOS)))
