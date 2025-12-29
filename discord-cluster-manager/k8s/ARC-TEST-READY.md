# ARC Test - Ready to Go! ✅

## Status Check

✅ **Kyverno Policy**: Active (`inject-amd-gpu-resources`)
✅ **Device Plugin**: Running (1 GPU exposed)
✅ **Node Label**: Set (`amd.com/gpu.present=true`)
✅ **ARC Runner**: Configured (`amd-arc-runner`)
✅ **Workflow File**: Ready (`.github/workflows/amd-mla-decode-workflow-ARC.yml`)

## What Will Happen

When you trigger the workflow:

1. **ARC creates a workflow pod** (name ends with `-workflow`)
2. **Kyverno policy automatically injects**:
   - GPU resource request/limit (`amd.com/gpu: "1"`)
   - seccomp unconfined
   - Large /dev/shm (8Gi)
   - Privileged mode
   - Node selector for GPU node
3. **Pod gets scheduled** on GPU node
4. **Workflow runs** with GPU access

## How to Test

### Option 1: Trigger via GitHub UI

1. Go to your repository on GitHub
2. Click **Actions** tab
3. Select **"AMD MLA-Decode Eval Job"** workflow
4. Click **"Run workflow"**
5. Fill in the inputs:
   - `run_id`: Any unique ID (e.g., "test-001")
   - `payload`: Your test payload JSON
   - `runner`: **"amd-arc-runner"** (already default)
   - `requirements`: (optional)
6. Click **"Run workflow"**

### Option 2: Monitor the Test

While the workflow runs, monitor it:

```bash
# Watch workflow pods
kubectl get pods -n arc-runners -w

# Check specific workflow pod logs
kubectl logs -f <workflow-pod-name> -n arc-runners

# Verify GPU allocation
kubectl describe pod <workflow-pod-name> -n arc-runners | grep -A 10 "Allocated resources"
```

## What to Look For

✅ **Success indicators**:
- Pod starts and runs successfully
- PyTorch detects GPU: `torch.cuda.is_available() == True`
- No GPU hang errors
- Workflow completes normally

❌ **If issues occur**:
- Check pod logs: `kubectl logs <pod-name> -n arc-runners`
- Check pod status: `kubectl describe pod <pod-name> -n arc-runners`
- Check GPU status: `timeout 5 amd-smi` (on host)
- Check kernel logs: `sudo dmesg -T | grep -i amdgpu`

## Notes

- The workflow file already has `container.options: --privileged --user root` which is fine - Kyverno will ensure proper security contexts
- The policy only applies to pods ending with `-workflow`, so runner pods won't get GPU resources
- With 1 GPU, only 1 workflow can run at a time (by design)

## Quick Verification Commands

```bash
# Check everything is ready
export KUBECONFIG=~/.kube/config

# Policy active?
kubectl get clusterpolicy inject-amd-gpu-resources

# Device plugin running?
kubectl get pods -n kube-system | grep amdgpu

# GPU resources available?
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:"status.capacity.amd\.com/gpu"

# Node labeled?
kubectl get nodes --show-labels | grep amd.com/gpu.present

# ARC runner ready?
kubectl get autoscalingrunnersets -n arc-runners
```

