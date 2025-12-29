# Complete Deployment Guide - AMD GPU + ARC on k3s

This guide will help you deploy the exact same setup on a brand new server.

## Prerequisites

- Ubuntu/Debian Linux server with AMD GPU (tested with MI300X)
- ROCm drivers installed and working on the host
- Root/sudo access
- GitHub Personal Access Token (PAT) with appropriate permissions

## Step 1: Install k3s

```bash
# Install k3s
curl -sfL https://get.k3s.io | sh -

# Set up kubectl access
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config

# Verify installation
kubectl get nodes
```

## Step 2: Install Helm

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

## Step 3: Install Kyverno

```bash
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update
helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --set replicaCount=1

# Wait for Kyverno to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=kyverno -n kyverno --timeout=120s
```

## Step 4: Install AMD GPU Device Plugin

```bash
cd discord-cluster-manager/k8s
chmod +x install-amd-gpu-device-plugin.sh
./install-amd-gpu-device-plugin.sh

# Verify GPU resources are exposed
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:"status.capacity.amd\.com/gpu"
```

Expected output: Should show `1` (or number of GPUs) under GPU column.

## Step 5: Label GPU Node

```bash
# Get your node name
NODE_NAME=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')

# Label the node
kubectl label nodes $NODE_NAME amd.com/gpu.present=true

# Verify
kubectl get nodes --show-labels | grep amd.com/gpu.present
```

## Step 6: Install ARC (Actions Runner Controller)

```bash
cd discord-cluster-manager/k8s

# Set your configuration
INSTALLATION_NAME="amd-arc-runner"
NAMESPACE="arc-runners"
GITHUB_CONFIG_URL="https://github.com/YOUR_ORG/YOUR_REPO"  # Change this!
GITHUB_PAT="ghp_YOUR_TOKEN_HERE"  # Change this!

# Run the installation script
chmod +x install-amd-arc.sh
./install-amd-arc.sh \
  --github-url "$GITHUB_CONFIG_URL" \
  --github-pat "$GITHUB_PAT" \
  --node-name "$NODE_NAME"
```

**Note**: The script will automatically apply the Kyverno policy for GPU injection.

Alternatively, install ARC manually:

```bash
# Step 6a: Install ARC Controller
helm repo add actions-runner-controller https://actions-runner-controller.github.io/actions-runner-controller
helm repo update

NAMESPACE_SYSTEM="arc-systems"
helm install arc \
  --namespace "${NAMESPACE_SYSTEM}" \
  --create-namespace \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller

# Step 6b: Create GitHub PAT Secret
NAMESPACE_RUNNERS="arc-runners"
GITHUB_PAT="ghp_YOUR_TOKEN_HERE"  # Change this!

kubectl create namespace "${NAMESPACE_RUNNERS}" --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic github-pat-secret \
  --namespace "${NAMESPACE_RUNNERS}" \
  --from-literal=github_token="${GITHUB_PAT}" \
  --dry-run=client -o yaml | kubectl apply -f -

# Step 6c: Install Runner Scale Set
INSTALLATION_NAME="amd-arc-runner"
GITHUB_CONFIG_URL="https://github.com/YOUR_ORG/YOUR_REPO"  # Change this!
STORAGE_CLASS="local-path"  # Default for k3s

helm install "${INSTALLATION_NAME}" \
  --namespace "${NAMESPACE_RUNNERS}" \
  --create-namespace \
  --set githubConfigUrl="${GITHUB_CONFIG_URL}" \
  --set githubConfigSecret.github_token="${GITHUB_PAT}" \
  --set containerMode.type="kubernetes" \
  --set containerMode.kubernetesModeWorkVolumeClaim.storageClassName="${STORAGE_CLASS}" \
  --set containerMode.kubernetesModeWorkVolumeClaim.accessModes[0]="ReadWriteOnce" \
  --set containerMode.kubernetesModeWorkVolumeClaim.resources.requests.storage="10Gi" \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
```

## Step 7: Apply Kyverno GPU Policy

The policy file includes all the k3s + ROCm fixes we discovered:

```bash
cd discord-cluster-manager/k8s
kubectl apply -f amd-gpu-kyverno-policy.yaml

# Verify policy is active
kubectl get clusterpolicy inject-amd-gpu-resources
```

**Important**: This policy includes:
- seccomp unconfined (fixes k3s containerd/runc issue)
- Large /dev/shm (8Gi) for PyTorch/ROCm
- Privileged mode with proper security contexts
- GPU resource requests via device plugin

## Step 8: Verify Everything

Run the verification script or manually check:

```bash
# 1. Kyverno Policy
kubectl get clusterpolicy inject-amd-gpu-resources

# 2. Device Plugin
kubectl get pods -n kube-system | grep amdgpu

# 3. GPU Resources
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:"status.capacity.amd\.com/gpu"

# 4. Node Label
kubectl get nodes --show-labels | grep amd.com/gpu.present

# 5. ARC Runner
kubectl get autoscalingrunnersets -n arc-runners

# 6. Test GPU access (optional but recommended)
kubectl apply -f test-rocm-k3s.yaml
kubectl logs -f rocm-torch-smoke -n arc-runners
kubectl delete pod rocm-torch-smoke -n arc-runners
```

## Step 9: Configure Workflow

Your GitHub workflow should use the runner label. Get it with:

```bash
kubectl get autoscalingrunnersets -n arc-runners -o jsonpath='{.items[0].metadata.name}'
```

Usually it's `amd-arc-runner` (matches installation name).

In your `.github/workflows/*.yml`:
```yaml
jobs:
  run:
    runs-on: amd-arc-runner  # Your runner label
    container:
      image: ghcr.io/leoxinhaolee/amd-runner:latest
      options: --privileged --user root
```

## Key Files Reference

- `amd-gpu-kyverno-policy.yaml` - Kyverno policy with all GPU fixes
- `install-amd-gpu-device-plugin.sh` - Device plugin installation
- `install-amd-arc.sh` - ARC installation script
- `recover-amd-arc.sh` - Recovery script after reboot
- `test-rocm-k3s.yaml` - Test pod to verify GPU works

## Quick Recovery After Reboot

If the server reboots:

```bash
cd discord-cluster-manager/k8s
./recover-amd-arc.sh
```

Or manually:
```bash
# Start k3s (if not auto-started)
sudo systemctl start k3s

# Reapply policy (if needed)
kubectl apply -f amd-gpu-kyverno-policy.yaml

# Check everything is running
kubectl get pods --all-namespaces
```

## Troubleshooting

### GPU not showing in Kubernetes
```bash
# Check device plugin logs
kubectl logs -n kube-system -l name=amdgpu-dp-ds

# Check GPU on host
amd-smi

# Restart device plugin if needed
kubectl delete pod -n kube-system -l name=amdgpu-dp-ds
```

### Pods can't get GPU
```bash
# Check policy is active
kubectl get clusterpolicy inject-amd-gpu-resources

# Check pod annotations (should have seccomp, etc.)
kubectl get pod <pod-name> -n arc-runners -o yaml | grep -A 10 securityContext

# Check GPU resources available
kubectl describe node | grep amd.com/gpu
```

### PyTorch GPU hangs
- Verify seccomp is unconfined in pod spec
- Verify /dev/shm is mounted (8Gi)
- Check kernel logs: `sudo dmesg -T | grep -i amdgpu`

## Summary of Key Fixes Applied

1. **k3s seccomp issue**: Added `seccompProfile.type: Unconfined` (k3s uses containerd+runc with different defaults)
2. **Shared memory**: Added large `/dev/shm` (8Gi) volume (PyTorch/ROCm needs more than default)
3. **Device plugin**: Using AMD k8s-device-plugin for proper GPU allocation
4. **Privileged mode**: Required for /dev/kfd and /dev/dri access
5. **No HSA_OVERRIDE_GFX_VERSION**: Removed unless actually needed (can cause hangs)

These fixes are all included in `amd-gpu-kyverno-policy.yaml`.

