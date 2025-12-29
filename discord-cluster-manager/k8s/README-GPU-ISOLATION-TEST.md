# GPU Isolation Test Guide

## Problem

When running 8 parallel requests, all pods are landing on the same GPU (GPU 0) instead of being distributed across all 8 GPUs.

## Root Cause

The AMD GPU device plugin should isolate GPUs automatically. Each pod should see exactly 1 GPU (its allocated GPU), even though inside the pod it's called "GPU 0".

If pods see `device_count() > 1`, the device plugin is NOT isolating GPUs properly.

## Testing Tools

### 1. Quick Check (for running workflow pods)

```bash
cd discord-cluster-manager/k8s
./check-running-pods-gpu.sh
```

This checks all currently running workflow pods and reports:
- Environment variables (ROCR_VISIBLE_DEVICES, HIP_VISIBLE_DEVICES)
- `torch.cuda.device_count()` in each pod
- Whether device plugin is isolating GPUs correctly

### 2. Comprehensive Test (create test pods)

```bash
cd discord-cluster-manager/k8s
./test-gpu-isolation.sh [NUM_PODS]
```

This will:
- Create multiple test pods (default: 4, override with argument)
- Each pod requests 1 GPU (`amd.com/gpu: "1"`)
- Check how many GPUs each pod sees
- Report if device plugin is working correctly

Example:
```bash
# Test with 4 pods
./test-gpu-isolation.sh 4

# Test with 8 pods (match your GPU count)
./test-gpu-isolation.sh 8
```

### 3. Single Test Pod (manual inspection)

```bash
cd discord-cluster-manager/k8s
kubectl apply -f test-gpu-isolation.yaml

# Wait for pod to be ready
kubectl wait --for=condition=Ready pod/gpu-isolation-test -n arc-runners --timeout=60s

# Check logs
kubectl logs gpu-isolation-test -n arc-runners

# Check device count manually
kubectl exec -n arc-runners gpu-isolation-test -- python3 -c "import torch; print('device_count:', torch.cuda.device_count() if torch.cuda.is_available() else 0)"

# Cleanup
kubectl delete pod gpu-isolation-test -n arc-runners
```

## Expected Results

### ✅ CORRECT Behavior

- Each pod sees `torch.cuda.device_count() == 1`
- `ROCR_VISIBLE_DEVICES` is either `not_set` or set by device plugin
- Each pod's "GPU 0" is actually a different physical GPU on the host
- Device plugin is working correctly!

### ❌ PROBLEM Behavior

- Pods see `torch.cuda.device_count() > 1`
- All pods see all 8 GPUs
- All pods land on the same physical GPU (GPU 0)
- Device plugin is NOT isolating GPUs

## What to Check

1. **Device Plugin Status**
   ```bash
   kubectl get pods -n kube-system -l name=amdgpu-dp-ds
   kubectl logs -n kube-system -l name=amdgpu-dp-ds
   ```

2. **GPU Resources**
   ```bash
   kubectl get nodes -o jsonpath='{.items[0].status.capacity.amd\.com/gpu}'
   kubectl describe node <node-name> | grep amd.com/gpu
   ```

3. **Pod Resources**
   ```bash
   kubectl get pods -n arc-runners -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[0].resources}{"\n"}{end}'
   ```

## Solution

If device plugin is NOT isolating GPUs:

1. **Check device plugin version/capabilities**
   - AMD device plugins may not support GPU isolation like NVIDIA's
   - Check device plugin documentation

2. **Alternative device plugin implementations**
   - Try different AMD GPU device plugins
   - Some may support better GPU isolation

3. **Manual GPU assignment (if device plugin doesn't support isolation)**
   - Use node labels per GPU
   - Or use pod affinity/anti-affinity
   - Or accept that all pods share GPUs (with proper scheduling limits)

## Notes

- The current Kyverno policy is correct - it does NOT set `ROCR_VISIBLE_DEVICES`
- The device plugin should handle GPU isolation automatically
- Do NOT manually set `ROCR_VISIBLE_DEVICES=0` - this forces all pods to GPU 0
