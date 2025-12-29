# GPU Allocation with Privileged Mode - How It Works

## Question: Does privileged mode give access to all GPUs?

**Answer: No, each pod is still limited to 1 GPU.**

## How GPU Allocation Works

### 1. Resource Requests/Limits (Primary Control)

The Kyverno policy still sets:
```yaml
resources:
  requests:
    amd.com/gpu: "1"
  limits:
    amd.com/gpu: "1"
```

**This is what Kubernetes uses to allocate GPUs:**
- Kubernetes scheduler only schedules pods when GPUs are available
- Device plugin allocates exactly 1 GPU per pod (can't over-commit)
- Kubernetes enforces the limit at the scheduler level

### 2. Device Plugin Isolation (Secondary Control)

The AMD GPU device plugin handles GPU isolation by:

1. **Allocating specific GPU(s)** when pod requests `amd.com/gpu: "1"`
2. **Setting environment variables** (typically `ROCR_VISIBLE_DEVICES` or similar) to limit which GPUs ROCm sees
3. **Device file access control** - even with privileged mode, ROCm respects the environment variables

### 3. Privileged Mode vs GPU Access

**Privileged mode gives:**
- Access to device files (`/dev/kfd`, `/dev/dri/*`)
- Root-level permissions

**Privileged mode does NOT:**
- Bypass device plugin GPU allocation
- Override `ROCR_VISIBLE_DEVICES` environment variables
- Allow accessing GPUs not allocated to the pod

## Why This Works

Even with privileged mode, the GPU device plugin:
1. Sets `ROCR_VISIBLE_DEVICES` to only the allocated GPU index(es)
2. ROCm runtime respects this environment variable
3. Applications using ROCm/PyTorch only see the allocated GPU(s)

## Example

If you have 8 GPUs on a node:

```bash
# Pod 1 requests amd.com/gpu: "1"
# Device plugin sets: ROCR_VISIBLE_DEVICES=0
# Pod 1 only sees GPU 0

# Pod 2 requests amd.com/gpu: "1"  
# Device plugin sets: ROCR_VISIBLE_DEVICES=1
# Pod 2 only sees GPU 1

# And so on...
```

Even though both pods have privileged access to all device files, ROCm only exposes the allocated GPU.

## Verification

To verify GPU isolation, you can test:

```bash
# Create a test pod
kubectl run test-gpu-isolation -n arc-runners \
  --image=ghcr.io/leoxinhaolee/amd-runner:latest \
  --restart=Never \
  --rm -it -- \
  python3 -c "import torch; print('GPU count:', torch.cuda.device_count())"

# Should print: GPU count: 1
```

Or check environment variables:
```bash
kubectl exec -n arc-runners <pod-name> -- env | grep ROCR
```

## Current Configuration

With the updated Kyverno policy:
- ✅ Each pod requests `amd.com/gpu: "1"`
- ✅ Device plugin allocates exactly 1 GPU per pod
- ✅ ROCm respects device plugin's GPU allocation
- ✅ Privileged mode only gives device file access, not additional GPU allocation

## Multi-GPU Node Scaling

When you scale to 8 GPUs:
- Each pod still requests `amd.com/gpu: "1"`
- Kubernetes scheduler can schedule up to 8 pods (1 per GPU)
- Each pod gets a different GPU via device plugin allocation
- No conflicts, proper isolation maintained



