# GPU Isolation Test Results

## Test Date
2025-12-29

## Test Configuration
- **Number of test pods**: 8
- **GPUs requested per pod**: 1 (`amd.com/gpu: "1"`)
- **Total GPUs on node**: 8

## Test Results

### ❌ PROBLEM CONFIRMED

**All 8 pods see `device_count() == 8`**

```
Pod gpu-isolation-test-0: device_count: 8
Pod gpu-isolation-test-1: device_count: 8
Pod gpu-isolation-test-2: device_count: 8
Pod gpu-isolation-test-3: device_count: 8
Pod gpu-isolation-test-4: device_count: 8
Pod gpu-isolation-test-5: device_count: 8
Pod gpu-isolation-test-6: device_count: 8
Pod gpu-isolation-test-7: device_count: 8
```

**Environment Variables:**
- `ROCR_VISIBLE_DEVICES`: `not_set` (all pods)
- `HIP_VISIBLE_DEVICES`: `not_set` (all pods)

**Device Files:**
- All pods can access all device files: `/dev/dri/renderD128` through `/dev/dri/renderD137`
- No restriction on device file access

### Device Plugin Behavior

From device plugin logs:
- ✅ Device plugin **IS allocating different GPUs** to different pods:
  - Pod 0: `0000:83:00.0`
  - Pod 1: `0000:8b:00.0`
  - Pod 2: `0000:93:00.0`
  - Pod 3: `0000:9b:00.0`
  - Pod 4: `0000:a3:00.0`
  - etc.

- ❌ **BUT** device plugin does NOT:
  - Restrict device file access (pods can see all device files)
  - Set `ROCR_VISIBLE_DEVICES` environment variable
  - Actually isolate GPUs at the runtime level

## Root Cause

The **AMD ROCm k8s-device-plugin** allocates GPUs for **scheduling purposes only**. It tracks which GPU is allocated to which pod for Kubernetes resource accounting, but it does **NOT**:
1. Restrict device file access
2. Set environment variables (`ROCR_VISIBLE_DEVICES`)
3. Provide runtime GPU isolation

This is different from NVIDIA's device plugin, which does provide runtime isolation.

## Impact

- All pods can see all 8 GPUs
- All pods default to using GPU 0
- No automatic GPU distribution
- Workloads compete for the same GPU

## Expected Behavior (Not Currently Working)

Each pod should:
- See `device_count() == 1` (only its allocated GPU)
- Have `ROCR_VISIBLE_DEVICES` set to the allocated GPU index
- Only be able to access its allocated GPU device files

## Possible Solutions

Since the device plugin doesn't isolate GPUs, we need a workaround:

1. **Manual GPU assignment via environment variables** (workaround)
   - Use Kyverno to inject `ROCR_VISIBLE_DEVICES` based on pod index/name
   - Problem: How to determine which GPU was allocated to each pod?

2. **Custom mutating admission webhook**
   - Read device plugin allocation information
   - Set `ROCR_VISIBLE_DEVICES` accordingly
   - More complex but would work

3. **Different device plugin implementation**
   - Some AMD device plugins may provide better isolation
   - Need to research alternatives

4. **Use pod names/hashes for round-robin assignment**
   - Simple workaround: assign GPU 0-7 based on pod name hash
   - Not perfect but would distribute workloads

## Current Status

✅ **Test completed and problem confirmed**
❌ **Device plugin does not isolate GPUs**
❌ **Need solution/workaround for GPU distribution**

## Next Steps

1. Research if AMD device plugin has configuration options for isolation
2. Consider implementing manual GPU assignment workaround
3. Check if there are alternative AMD device plugin implementations
4. Discuss with team about acceptable workarounds

