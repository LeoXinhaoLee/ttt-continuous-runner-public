# AMD GPU ARC Configuration Files

This directory contains configuration files for setting up Actions Runner Controller (ARC) with AMD GPUs.

## Files Overview

- **`KUBERNETES-SETUP.md`**: Guide for installing Kubernetes (if you don't have a cluster yet)
- **`amd-arc-setup.md`**: Complete setup guide with detailed instructions
- **`QUICKSTART.md`**: Quick reference guide for getting started
- **`amd-gpu-kyverno-policy.yaml`**: Kyverno policy for GPU resource injection (1 GPU per pod)
- **`amd-gpu-limitrange.yaml`**: LimitRange for default GPU resource requests
- **`amd-gpu-test-pod.yaml`**: Test pod to verify GPU allocation
- **`check-gpu-resources.sh`**: Script to check GPU resources on nodes
- **`install-amd-arc.sh`**: Automated installation script

## Getting Started

### 1. Install Kubernetes (if needed)

If you don't have a Kubernetes cluster yet, see `KUBERNETES-SETUP.md` for installation options.

**Quick start with k3s (recommended for single node):**
```bash
curl -sfL https://get.k3s.io | sh -
sudo k3s kubectl get nodes
```

### 2. Install Kubernetes Tools

```bash
# kubectl (usually included with k3s/microk8s)
# For k3s: sudo k3s kubectl
# For microk8s: sudo snap alias microk8s.kubectl kubectl

# Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### 3. Check GPU Resources

```bash
cd discord-cluster-manager/k8s
chmod +x check-gpu-resources.sh
./check-gpu-resources.sh
```

### 4. Install ARC

```bash
chmod +x install-amd-arc.sh
./install-amd-arc.sh \
  --github-url "https://github.com/YOUR_ORG/YOUR_REPO" \
  --github-pat "ghp_YOUR_TOKEN" \
  --node-name "YOUR_NODE_NAME"
```

See `QUICKSTART.md` for more details.

## Important: AMD GPU Resource Names

AMD GPU device plugins are less standardized than NVIDIA's. The configuration files use `amd.com/gpu` as the default resource name, but you may need to adjust this based on your setup.

**To check your GPU resource name:**
```bash
kubectl describe node <node-name> | grep -i gpu
```

**Common alternatives:**
- `rocm/gpu`
- `amd.com/rocm`
- Custom name from your device plugin

If you don't see any GPU resources, you may need to:
1. Install an AMD GPU device plugin
2. Or manually configure GPU allocation (more complex)

## Scaling

- **1 Node, 1 GPU**: Current configuration (default)
- **1 Node, 8 GPUs**: No code changes needed, ARC automatically scales
- **2 Nodes, 16 GPUs**: Label additional nodes with `amd.com/gpu.present=true`
