# Quick Deployment Guide

## Automated Deployment (Recommended)

For a brand new server, use the automated script:

```bash
cd discord-cluster-manager/k8s

./deploy-from-scratch.sh \
  --github-url "https://github.com/YOUR_ORG/YOUR_REPO" \
  --github-pat "ghp_YOUR_TOKEN_HERE" \
  --skip-tests  # Optional: skip GPU test
```

This script will:
1. Install k3s (if not already installed)
2. Install Helm
3. Install Kyverno
4. Install AMD GPU Device Plugin
5. Label the GPU node
6. Install ARC (Actions Runner Controller)
7. Apply Kyverno GPU policy (with all k3s fixes)
8. Verify everything is working

## Manual Deployment

If you prefer step-by-step, see `DEPLOYMENT-GUIDE.md` for detailed instructions.

## What Gets Installed

- **k3s**: Lightweight Kubernetes
- **Helm**: Package manager
- **Kyverno**: Policy engine for GPU injection
- **AMD GPU Device Plugin**: Exposes GPUs to Kubernetes
- **ARC**: GitHub Actions runner controller
- **GPU Policy**: Kyverno policy with:
  - seccomp unconfined (k3s fix)
  - Large /dev/shm (8Gi)
  - Privileged mode
  - GPU resource allocation

## After Deployment

1. **Get runner label**:
   ```bash
   kubectl get autoscalingrunnersets -n arc-runners -o jsonpath='{.items[0].metadata.name}'
   ```

2. **Update workflow** to use the runner label:
   ```yaml
   jobs:
     run:
       runs-on: amd-arc-runner  # Your runner label
   ```

3. **Test with a workflow run**

## Recovery After Reboot

If the server reboots:

```bash
cd discord-cluster-manager/k8s
./recover-amd-arc.sh
```

Or manually:
```bash
sudo systemctl start k3s  # If not auto-started
kubectl apply -f amd-gpu-kyverno-policy.yaml
```

## Files Included

- `deploy-from-scratch.sh` - Automated deployment script
- `DEPLOYMENT-GUIDE.md` - Detailed step-by-step guide
- `recover-amd-arc.sh` - Recovery script after reboot
- `amd-gpu-kyverno-policy.yaml` - GPU policy with all fixes
- `install-amd-gpu-device-plugin.sh` - Device plugin installer
- `install-amd-arc.sh` - ARC installer
- `test-rocm-k3s.yaml` - GPU test pod

