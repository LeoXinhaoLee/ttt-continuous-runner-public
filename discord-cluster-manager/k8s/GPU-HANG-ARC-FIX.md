# GPU Hang Fix for ARC Setup

## Problem

GPU hangs occur only with ARC setup, not with direct `amd-docker` runner. This is because:

1. **ARC doesn't translate Docker `--privileged` flag properly**: The workflow specifies `container.options: --privileged`, but ARC creates Kubernetes pods, and the `--privileged` Docker option doesn't automatically translate to Kubernetes `securityContext.privileged`.

2. **Conflicting device access methods**: The original Kyverno policy explicitly mounted `/dev/kfd` and `/dev/dri` as hostPath volumes. When combined with attempts to use privileged mode, this can cause conflicts where:
   - Device mounts might interfere with device plugin allocation
   - Multiple access paths to the same devices can corrupt GPU driver state
   - Pod termination doesn't properly clean up GPU state

## Solution

Updated the Kyverno policy to use **container-level privileged mode** instead of explicit device mounts:

```yaml
containers:
  - (name): "*"
    securityContext:
      privileged: true  # This gives access to ALL devices including /dev/kfd and /dev/dri
```

**Why this works:**
- Privileged containers have access to all host devices automatically
- No need for explicit device mounts, reducing conflicts
- Simpler configuration that matches how the working `amd-docker` setup works
- Better device cleanup on pod termination

## Changes Made

**File**: `discord-cluster-manager/k8s/amd-gpu-kyverno-policy.yaml`

**Removed**:
- Explicit `volumeMounts` for `/dev/kfd` and `/dev/dri`
- Explicit `volumes` definitions for device files

**Added**:
- `securityContext.privileged: true` at container level
- Pod-level `securityContext` for consistency

## Testing

After applying the updated policy, test with a workflow run:

```bash
# Verify policy is applied
kubectl get clusterpolicy inject-amd-gpu-resources -o yaml

# Run a test workflow and monitor for GPU hangs
# Check pod spec to verify privileged mode is set
kubectl get pod -n arc-runners -l <selector> -o yaml | grep -A 10 securityContext
```

## Additional Notes

- The workflow file (`amd-mla-decode-workflow-ARC.yml`) still has `options: --privileged`, but this is now redundant since Kyverno sets it at the pod level. It doesn't hurt to keep it.
- If GPU hangs persist, consider removing the `--privileged` flag from the workflow and rely entirely on Kyverno policy.
- This approach matches how privileged containers work in direct Docker setups.

