# GPU Hang Recovery Guide

This guide addresses GPU hang issues on AMD MI300X GPUs when running ARC workflows.

## Symptoms

- Workflow execution hangs with "GPU Hang" error
- `amd-smi` or `rocm-smi` commands hang
- GPU becomes completely unresponsive
- Processes using GPU devices become stuck

## Immediate Recovery Steps

### 1. Check Current GPU State

```bash
cd /home/runner/ttt-continuous-runner-public/discord-cluster-manager/k8s
./gpu-hang-recovery.sh
```

### 2. Kill Stuck Processes

```bash
# Find processes using GPU
lsof /dev/kfd /dev/dri/renderD* 2>&1 | grep -v "COMMAND"

# Kill specific processes (replace PID)
kill -9 <PID>

# If amd-smi is hanging, force kill it
killall -9 amd-smi
```

### 3. Clean Up Kubernetes Pods

```bash
export KUBECONFIG=~/.kube/config

# Check for stuck pods
kubectl get pods --all-namespaces | grep -E "Error|CrashLoopBackOff|Pending"

# Delete stuck workflow pods
kubectl delete pods -n arc-runners --field-selector status.phase!=Running
```

### 4. Restart GPU Device Plugin

```bash
export KUBECONFIG=~/.kube/config
kubectl rollout restart daemonset/amdgpu-device-plugin-daemonset -n kube-system

# Wait for it to restart
kubectl rollout status daemonset/amdgpu-device-plugin-daemonset -n kube-system
```

### 5. Check System Logs

```bash
# Check for GPU errors
sudo dmesg | tail -100 | grep -i "amdgpu\|gpu\|hang"

# Check journal logs
sudo journalctl -b -0 | grep -i "amdgpu\|gpu hung" | tail -50
```

### 6. Restart k3s (if GPU still hung)

```bash
sudo systemctl restart k3s
sleep 10
export KUBECONFIG=~/.kube/config
kubectl get nodes
```

### 7. Full Server Reboot (last resort)

If the GPU is completely unresponsive:

```bash
sudo reboot
```

After reboot, run the recovery script:
```bash
cd /home/runner/ttt-continuous-runner-public/discord-cluster-manager/k8s
./recover-amd-arc.sh
```

## Prevention Strategies

### 1. Add Timeouts to Workflows

The workflow already has a `timeout-minutes: 30` setting. Ensure workloads have reasonable timeouts to prevent indefinite hangs.

### 2. Resource Cleanup

Ensure PyTorch properly releases GPU resources:

```python
import torch
import gc

# After GPU operations
torch.cuda.empty_cache()
gc.collect()
```

### 3. Container Resource Limits

The Kyverno policy already sets GPU limits to 1. Ensure containers don't exceed these limits.

### 4. GPU Reset on Pod Termination

Consider adding a preStop hook to cleanup GPU resources:

```yaml
lifecycle:
  preStop:
    exec:
      command: ["/bin/sh", "-c", "python3 -c 'import torch; torch.cuda.empty_cache()' || true"]
```

### 5. Monitor GPU Health

Add health checks to detect GPU issues early:

```bash
# Check GPU health periodically
rocminfo || echo "GPU not accessible"
rocm-smi || echo "GPU management tool failed"
```

## Root Causes

Common causes of GPU hangs on MI300X:

1. **Driver Issues**: Outdated or incompatible AMD GPU driver
2. **Resource Leaks**: GPU memory not properly freed
3. **Kernel Conflicts**: Kernel-level driver conflicts
4. **Hardware Issues**: Physical GPU problems (rare)
5. **Concurrent Access**: Multiple processes accessing GPU simultaneously
6. **Timeout Issues**: Long-running operations without proper cleanup

## Diagnostic Commands

```bash
# Check GPU devices
ls -la /dev/kfd /dev/dri/renderD*

# Check GPU driver version
modinfo amdgpu | grep version

# Check ROCm version
rocminfo --version || echo "ROCm not accessible"

# Check for GPU processes
ps aux | grep -E "python.*cuda|rocm|amd"

# Check Kubernetes GPU allocation
kubectl describe node | grep -A 10 "amd.com/gpu"
```

## When to Escalate

Consider these actions if hangs persist:

1. **Update GPU Driver**: Check for driver updates from AMD
2. **Update ROCm**: Ensure ROCm version is compatible with MI300X
3. **Check Hardware**: Verify GPU hardware is functioning correctly
4. **Contact Support**: Reach out to AMD/ROCm support for MI300X-specific issues

## Known Issues

- MI300X requires specific driver versions (amdgpu-build >= 6.12.12)
- `HSA_OVERRIDE_GFX_VERSION=11.0.0` is required for gfx1100 (MI300X)
- Some kernel versions may have GPU hang issues

## Related Files

- `discord-cluster-manager/k8s/gpu-hang-recovery.sh` - Recovery script
- `discord-cluster-manager/k8s/amd-gpu-kyverno-policy.yaml` - GPU resource injection
- `.github/workflows/amd-mla-decode-workflow-ARC.yml` - Workflow definition



