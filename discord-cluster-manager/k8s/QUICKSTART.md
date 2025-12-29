# Quick Start: AMD ARC Setup (1 Node, 1 GPU)

Quick reference for setting up ARC with 1 node and 1 GPU.

## Prerequisites Check

```bash
# Check kubectl access
kubectl cluster-info

# Check helm
helm version

# Check node name
kubectl get nodes
```

## Installation

```bash
cd discord-cluster-manager/k8s

# Make script executable (if needed)
chmod +x install-amd-arc.sh

# Run installation
./install-amd-arc.sh \
  --github-url "https://github.com/LeoXinhaoLee/ttt-continuous-runner-public" \
  --github-pat "ghp_YOUR_TOKEN_HERE" \
  --node-name "YOUR_NODE_NAME"
```

## Get Runner Label for Workflow

```bash
# Get the runner label (use this in your workflow's runs-on field)
kubectl get autoscalingrunnersets -n arc-runners -o jsonpath='{.items[0].status.runnerLabel}'

# Or check all details
kubectl get autoscalingrunnersets -n arc-runners -o yaml | grep runnerLabel
```

## Fix kubectl Permissions (If Needed)

If you get permission errors with kubectl:
```bash
cd discord-cluster-manager/k8s
./fix-kubeconfig-permissions.sh
```

Or manually:
```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
chmod 600 ~/.kube/config
export KUBECONFIG=~/.kube/config
```

## Verify Setup

```bash
# Check runner scale set
kubectl get autoscalingrunnersets -n arc-runners

# Check pods
kubectl get pods -n arc-runners

# Check node labels
kubectl get nodes --show-labels | grep amd

# Check GPU resources (adjust resource name if needed)
kubectl describe node YOUR_NODE_NAME | grep -i gpu
```

## Update Workflow

Update `.github/workflows/amd-mla-decode-workflow.yml`:

```yaml
jobs:
  run:
    runs-on: <runner-label-from-above>  # Replace with actual label
```

## Install GPU Device Plugin (Recommended)

To get Kubernetes-level GPU resource management:

```bash
cd discord-cluster-manager/k8s
./install-amd-gpu-device-plugin.sh
```

Or manually:
```bash
kubectl create -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-dp.yaml
```

Verify GPU resources:
```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:"status.capacity.amd\.com/gpu"
```

## Important Notes

1. **GPU Resource Name**: The official AMD device plugin uses `amd.com/gpu` as the resource name, which matches our configuration.

2. **Check Available Resources**: Run `kubectl describe node YOUR_NODE_NAME | grep amd.com/gpu` to see if GPU resources are available.

3. **Container Image**: The workflow uses `ghcr.io/leoxinhaolee/amd-runner:latest` which should work with ARC's container mode.

## Scaling Up

### To 1 Node, 8 GPUs
- No code changes needed - ARC will automatically create up to 8 pods (1 per GPU)

### To 2 Nodes, 16 GPUs
- Label the second node:
  ```bash
  kubectl label nodes NODE_2_NAME amd.com/gpu.present=true
  ```
- ARC will automatically distribute pods across both nodes

## Troubleshooting

```bash
# Check Kyverno policy
kubectl get clusterpolicy inject-amd-gpu-resources -o yaml

# Check pod events
kubectl get events -n arc-runners --sort-by='.lastTimestamp'

# Check pod logs
kubectl logs -n arc-runners <pod-name>

# Describe pod for details
kubectl describe pod -n arc-runners <pod-name>
```

