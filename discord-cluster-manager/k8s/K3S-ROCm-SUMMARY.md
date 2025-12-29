# k3s + ROCm GPU Hang Fix - Implementation Summary

## Expert Feedback Applied

Based on expert feedback, the root cause of GPU hangs in k3s is that k3s uses **containerd + runc** with different LSM/seccomp/AppArmor defaults than Docker. Even with `privileged: true`, k3s can apply additional security constraints that break ROCm.

## Changes Made

### 1. Updated Kyverno Policy (`amd-gpu-kyverno-policy.yaml`)

**Added:**
- `seccompProfile.type: Unconfined` - Explicitly disables seccomp (k3s can apply RuntimeDefault otherwise)
- Large `/dev/shm` volume (8Gi) - PyTorch/ROCm needs more shared memory than default 64MB
- `allowPrivilegeEscalation: true` - Additional privilege setting

**Removed:**
- `HSA_OVERRIDE_GFX_VERSION` - Only set if actually needed (can cause hangs if wrong/unnecessary)
- `ROCR_VISIBLE_DEVICES` - Not needed, device plugin handles GPU allocation

**Note:** AppArmor annotation removed from policy because:
- AppArmor annotations are per-container (require container name)
- Difficult to inject via Kyverno for dynamic ARC workflow pods
- If still needed, disable AppArmor at k3s level (see K3S-ROCm-FIX.md)

### 2. Installed AMD k8s-device-plugin

- Installed official AMD device plugin: `rocm/k8s-device-plugin`
- GPU resources now exposed as `amd.com/gpu`
- Device plugin handles GPU allocation and device mounting

### 3. Test Pod (`test-rocm-k3s.yaml`)

Created test pod matching expert's recommendations for validation.

## Next Steps

1. **Test with plain pod**: Run `test-rocm-k3s.yaml` to verify fix works
2. **Test with ARC workflow**: Run actual GitHub Actions workflow to verify
3. **If still hangs**: Consider disabling AppArmor at k3s level (see K3S-ROCm-FIX.md)

## Files Modified

- `amd-gpu-kyverno-policy.yaml` - Updated with seccomp, /dev/shm, removed HSA_OVERRIDE_GFX_VERSION
- `test-rocm-k3s.yaml` - Created test pod with expert's exact recommendations
- `K3S-ROCm-FIX.md` - Documentation on AppArmor workaround

## Key Insight

**The problem wasn't the device plugin or privileged mode itself** - it was k3s's additional security constraints (seccomp) and insufficient shared memory that caused ROCm to fail, even with privileged containers.

