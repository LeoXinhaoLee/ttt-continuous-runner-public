# GPU Hang Root Cause Analysis

## The Problem

We experienced GPU hangs during ARC workflow execution. The GPU would become unresponsive, and `amd-smi` would hang.

## What We Don't Know

**Important**: We cannot definitively say what caused the GPU hang. When we investigated:
- The GPU was already hung from a previous workflow run
- Multiple components were active (device plugin, Kyverno policy, workflow pods)
- We cannot isolate which component (if any) caused the hang

## Possible Causes

The GPU hang could have been caused by:

### 1. Device Plugin Issues
- **Theory**: AMD GPU device plugin (`rocm/k8s-device-plugin`) might have conflicts with privileged containers
- **Evidence**: Device plugin was running when hang occurred
- **Counter-evidence**: We removed it, but GPU was already hung, so no proof it caused it
- **Status**: Unknown - device plugin removed as precaution

### 2. Kyverno Policy Configuration
- **Theory**: Conflicting device access methods (explicit device mounts + privileged mode + device plugin allocation)
- **Timeline**: We changed from explicit device mounts to privileged mode during troubleshooting
- **Evidence**: Original policy had explicit `/dev/kfd` and `/dev/dri` mounts
- **Status**: Changed to privileged-only approach (simpler, matches working setup)

### 3. Workflow Code / PyTorch
- **Theory**: PyTorch not properly cleaning up GPU resources on pod termination
- **Evidence**: GPU hang occurred during/after workflow execution
- **Status**: Could still be an issue - would need to test with proper cleanup

### 4. Driver / Kernel Issues
- **Theory**: AMD GPU driver or kernel has bugs causing hangs
- **Evidence**: MI300X is relatively new, driver support may have issues
- **Status**: Unknown - would need driver/kernel updates to test

### 5. Resource Conflicts
- **Theory**: Multiple processes accessing GPU simultaneously
- **Evidence**: Device plugin + workflow pods + privileged containers
- **Status**: Reduced by removing device plugin

## What We Changed

1. **Removed device plugin**: As a precaution, removed AMD GPU device plugin
2. **Switched to no-device-plugin policy**: Simpler configuration that matches working `amd-docker` setup
3. **Privileged mode only**: Removed explicit device mounts, use privileged containers only
4. **Workflow pod matching**: Policy now only targets pods ending with `-workflow`

## Current State

- ✅ GPU works after reboot
- ✅ No-device-plugin setup is active
- ✅ Policy uses privileged containers (matches working setup)
- ❓ **Unknown if hang will recur** - need to test with actual workflows

## Testing Required

To determine the actual root cause, we would need to:

1. **Test current setup**: Run workflows and see if hang recurs
2. **If hang recurs**: It's not the device plugin, investigate:
   - PyTorch cleanup in workflow code
   - Driver/kernel issues
   - Other Kubernetes/ARC issues
3. **If hang doesn't recur**: Could be device plugin, but could also be:
   - The policy change (privileged-only vs explicit mounts)
   - A one-time driver issue that reboot fixed
   - Something else

## Recommendation

**Current approach (no-device-plugin) is good because**:
- Simpler and easier to debug
- Matches the working `amd-docker` setup
- One less component that could cause issues
- Can always add device plugin back later if needed

**But we should**:
- Monitor for future hangs
- If hangs recur, investigate workflow code and PyTorch cleanup
- Consider adding PyTorch cleanup hooks to pods
- Keep device plugin option available if we need Kubernetes GPU resource management later

