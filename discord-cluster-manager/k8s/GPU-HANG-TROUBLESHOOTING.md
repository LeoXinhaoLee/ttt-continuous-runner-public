# GPU Hang Troubleshooting

## Current Situation

GPU hangs occurred during workflow execution. After investigating, we switched to a no-device-plugin setup.

## Important Note: Unknown Root Cause

**We don't actually know what caused the GPU hang.** When the hang occurred:
- The GPU was already hung from a previous workflow run
- The device plugin was running, but we can't prove it caused the hang
- The hang could have been caused by:
  - The device plugin
  - The Kyverno policy configuration (conflicting device mounts + privileged mode)
  - The workflow code/PyTorch not cleaning up GPU resources properly
  - Driver/kernel issues
  - Something else entirely

## Immediate Actions Taken

1. ✅ Removed AMD GPU device plugin DaemonSet (as a precaution)
2. ✅ Switched to `amd-gpu-kyverno-policy-no-device-plugin.yaml` (no device plugin)
3. ✅ GPU works after reboot with no-device-plugin setup

## Why We Switched to No-Device-Plugin

**Not because we proved the device plugin was the problem**, but because:
1. **Matches working setup**: The `amd-docker` setup that works doesn't use a device plugin
2. **Simpler configuration**: Fewer components = fewer potential failure points
3. **No resource conflicts**: Without device plugin, no conflicts with privileged containers
4. **Easier debugging**: Less moving parts to troubleshoot

## Solution: Use No-Device-Plugin Policy

We've switched to the policy that **doesn't require a device plugin**:

**File**: `amd-gpu-kyverno-policy-no-device-plugin.yaml`

**How it works**:
- Uses node selector to schedule pods on GPU nodes
- No GPU resource requests/limits (not managed by Kubernetes)
- Relies on ARC max runners to limit concurrent pods
- Uses privileged containers (same as working `amd-docker` setup)

## Next Steps

### Option 1: Reboot Again (Recommended)

Since we removed the device plugin, reboot again to get a clean GPU state:

```bash
sudo reboot
```

After reboot:
```bash
cd /home/runner/ttt-continuous-runner-public/discord-cluster-manager/k8s
./recover-amd-arc.sh
```

**Note**: The recovery script will reapply the Kyverno policy, which is now the no-device-plugin version.

### Option 2: Configure ARC Max Runners

Since we're not using device plugin for GPU allocation, configure ARC to limit concurrent pods:

```bash
export KUBECONFIG=~/.kube/config

# Check current ARC runner set
kubectl get autoscalingrunnersets -n arc-runners -o yaml

# Set max runners to 1 (for 1 GPU) or match your GPU count
# This requires updating the ARC Helm release
```

### Option 3: Test Without Device Plugin

After reboot, test if GPU works without device plugin:

```bash
# Check GPU access
timeout 5 amd-smi || echo "Still hanging"

# If working, test a workflow
# GPU allocation will be manual (via ARC max runners)
```

## Why This Approach Works

The `amd-docker` setup that works uses:
- Direct Docker containers with `--privileged`
- No Kubernetes device plugin
- Manual GPU allocation (one container per GPU)

The no-device-plugin policy mimics this:
- Privileged containers ✅
- No device plugin ✅  
- Manual pod limiting via ARC max runners ✅

## Comparison

| Approach | GPU Allocation | Status |
|----------|---------------|--------|
| Device Plugin (old) | Kubernetes manages | ❌ Causes GPU hangs |
| No Device Plugin (new) | Manual (ARC max runners) | ✅ Should work like `amd-docker` |

## Recovery After Reboot

After reboot, the GPU should be in a clean state. The no-device-plugin policy will be active, which should prevent future hangs.


