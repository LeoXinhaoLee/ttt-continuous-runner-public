# GPU Isolation Fix - Expert Feedback Implementation

## Problem Identified

**Root Cause**: Using `privileged: true` was giving containers broad access to ALL GPU device files, bypassing the device plugin's intended GPU isolation mechanism.

## Expert Feedback

The AMD device plugin **DOES** isolate GPUs, but `privileged: true` bypasses this by giving access to all device files.

**Solution**: Remove `privileged: true` and let the device plugin handle device file restrictions.

## Changes Made

### Updated `amd-gpu-kyverno-policy.yaml`

**Removed:**
- `securityContext.privileged: true` ❌
- `allowPrivilegeEscalation: true` ❌
- Excessive capabilities (SYS_RESOURCE, SYS_PTRACE) ❌
- Pod-level `runAsUser: 0` (kept in container context where needed) ❌

**Kept:**
- `seccompProfile.type: Unconfined` ✅ (needed for k3s/ROCm compatibility)
- Container-level `runAsUser: 0` ✅ (needed for /dev/kfd access)
- `supplementalGroups: [992]` ✅ (allows access to /dev/dri/renderD*)
- Minimal `capabilities.add: [SYS_ADMIN]` ✅ (minimal capability)
- `amd.com/gpu: "1"` resource requests/limits ✅
- Large `/dev/shm` volume ✅
- NO `ROCR_VISIBLE_DEVICES` or `HIP_VISIBLE_DEVICES` ✅

## Test Results

### Before (Privileged Mode)
- All pods see `device_count() == 8` ❌
- All pods can access all device files ❌
- All pods default to GPU 0 ❌

### After (Non-Privileged Mode)
- Each pod sees `device_count() == 1` ✅
- Each pod can only access its allocated device file ✅
- Device plugin properly isolates GPUs ✅

## How It Works Now

1. **Device Plugin Allocates GPUs**: Tracks which GPU is allocated to each pod (for scheduling)
2. **Device Plugin Restricts Device Files**: Only mounts the allocated GPU's device files into the pod
3. **Container Sees Only Its GPU**: PyTorch/ROCm sees only 1 GPU (its allocated GPU)
4. **Each Pod's "GPU 0" is Different**: Pod 1's GPU 0 = Physical GPU 0, Pod 2's GPU 0 = Physical GPU 1, etc.

## Key Insight

The device plugin **restricts device file access at the mount level**, not via environment variables. By using `privileged: true`, we were bypassing this mechanism and giving access to all devices.

## Next Steps

1. ✅ Policy updated - All new workflow pods will use non-privileged mode
2. ⏳ Existing workflow pods will need to be recreated to pick up the new policy
3. ⏳ Test with actual ARC workflows to verify GPU distribution works

## Verification

To verify GPU isolation is working:
```bash
# Check a workflow pod
kubectl exec -n arc-runners <workflow-pod-name> -- python3 -c "import torch; print('device_count:', torch.cuda.device_count() if torch.cuda.is_available() else 0)"

# Should return: device_count: 1
```

If you see `device_count() == 1`, GPU isolation is working correctly! 🎉

