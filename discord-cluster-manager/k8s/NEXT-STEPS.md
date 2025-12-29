# Next Steps After k3s + ROCm Fix

## Current Status

✅ **Completed:**
- AMD k8s-device-plugin installed and running
- Kyverno policy updated with seccomp unconfined and large /dev/shm
- HSA_OVERRIDE_GFX_VERSION removed
- GPU resources visible (1 GPU)

⚠️ **Testing:**
- Plain pod test (`test-rocm-k3s.yaml`) still failing with exit code 141 (SIGPIPE/timeout)
- PyTorch operations timing out in container

## Immediate Next Steps

### Option 1: Test with Real ARC Workflow (Recommended)

The Kyverno policy changes are now active. Test with an actual GitHub Actions workflow:

1. **Trigger a workflow** that uses GPU
2. **Monitor the workflow pod**:
   ```bash
   kubectl get pods -n arc-runners -w
   kubectl logs -f <workflow-pod-name> -n arc-runners
   ```

3. **If it works**: The fix is successful! ✅
4. **If it still hangs**: Proceed to Option 2

### Option 2: Disable AppArmor at k3s Level

If GPU hangs persist, disable AppArmor globally:

1. **Check current k3s containerd config**:
   ```bash
   sudo cat /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
   ```

2. **Edit the template** (if it exists) or create it:
   ```bash
   sudo mkdir -p /var/lib/rancher/k3s/agent/etc/containerd
   sudo nano /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
   ```

3. **Add AppArmor disable** (if not already present):
   ```toml
   [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc]
     [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
       SystemdCgroup = true
       # Disable AppArmor
       NoNewPrivileges = false
   ```

4. **Restart k3s**:
   ```bash
   sudo systemctl restart k3s
   ```

5. **Wait for k3s to be ready**:
   ```bash
   kubectl get nodes
   ```

6. **Re-test** with `test-rocm-k3s.yaml` or ARC workflow

### Option 3: Check Kernel Logs (If GPU Hangs)

If the GPU becomes unresponsive after PyTorch operations:

```bash
# Check kernel logs (requires sudo)
sudo dmesg -T | grep -iE "amdgpu|kfd|gpu reset|ring|sdma|fault|timeout" | tail -50

# Or use journalctl
sudo journalctl -k -b | tail -100
```

Look for:
- GPU reset failures
- Timeout errors
- Ring/SDMA faults
- KFD errors

## Verification Commands

```bash
# Check GPU resources
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:"status.capacity.amd\.com/gpu"

# Check device plugin
kubectl get pods -n kube-system | grep amdgpu

# Check Kyverno policy
kubectl get clusterpolicy inject-amd-gpu-resources

# Check GPU status on host
timeout 5 amd-smi || echo "GPU hung"
```

## What Changed

The key fixes applied:
1. **seccomp unconfined** - k3s was applying RuntimeDefault seccomp profile
2. **Large /dev/shm (8Gi)** - PyTorch/ROCm need more shared memory
3. **Device plugin** - Proper GPU resource allocation
4. **Removed HSA_OVERRIDE_GFX_VERSION** - Can cause hangs if wrong

## If Still Not Working

1. **Check if AppArmor is the issue**: Disable at k3s level (Option 2)
2. **Check kernel logs**: Look for driver/ROCm errors (Option 3)
3. **Verify ROCm version compatibility**: Ensure ROCm version matches GPU
4. **Consider ROCm version**: May need different ROCm version for MI300X

