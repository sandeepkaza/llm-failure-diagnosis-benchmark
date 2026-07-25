#!/usr/bin/env bash
# Paper 5 VM setup: k3s (for fault injection + evidence capture) + Ollama
# (OpenAI-compatible open-model diagnosers). Run on the vast VM as root.
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "== host =="
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader

apt-get update -qq
apt-get install -yqq python3 curl jq >/dev/null

# --- k3s (single-node; real VM so kubelet runs, per the P6 finding) ---
if ! command -v k3s >/dev/null; then
  curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644 >/dev/null 2>&1
fi
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
echo "export KUBECONFIG=$KUBECONFIG" >> /root/.bashrc
ln -sf /usr/local/bin/k3s /usr/local/bin/kubectl 2>/dev/null || true
for i in $(seq 1 30); do
  kubectl get nodes 2>/dev/null | grep -q ' Ready ' && break; sleep 4
done
echo "== k3s node =="; kubectl get nodes

# --- Ollama (serves open models on the GPU, OpenAI-compatible at :11434/v1) ---
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh >/dev/null 2>&1
fi
systemctl enable --now ollama 2>/dev/null || (nohup ollama serve >/var/log/ollama.log 2>&1 &)
sleep 5
echo "== ollama =="; ollama --version 2>&1 | head -1

echo "SETUP OK"
