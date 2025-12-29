# GPU Resource Setup Notes

## Current Status

Based on the GPU resource check, **no GPU resources are currently exposed in Kubernetes**. This means:

- ✅ Node is running (rocm-7-1-software-gpu-mi300x1-192gb-devcloud-atl1)
- ✅ k3s is working
- ❌ No AMD GPU device plugin installed
- ❌ No GPU resources visible to Kubernetes

## Two Approaches for GPU Allocation

### Approach 1: Without GPU Device Plugin (Current Setup)

**When to use**: No device plugin installed, or device plugin unavailable.

**How it works**:
- Use node selectors to schedule pods on GPU nodes
- Container manages GPU access directly (via ROCR_VISIBLE_DEVICES or similar)
- No Kubernetes-level GPU resource requests/limits
- Relies on limiting concurrent pods per node

**Configuration**:
- Use: `amd-gpu-kyverno-policy-no-device-plugin.yaml`
- This policy only adds node selector (no resource requests/limits)
- Label nodes: `kubectl label nodes <node-name> amd.com/gpu.present=true`
- Limit concurrent pods manually (e.g., via ARC max runners)

**Pros**:
- Works immediately
- No additional components needed
- Simple setup

**Cons**:
- No Kubernetes-level GPU resource management
- Need to manually limit concurrent pods
- Less precise GPU allocation

### Approach 2: With GPU Device Plugin (Recommended for Production)

**When to use**: Want Kubernetes-level GPU resource management.

**How it works**:
- Device plugin exposes GPU resources (e.g., `amd.com/gpu`, `rocm/gpu`)
- Kubernetes scheduler manages GPU allocation
- Use resource requests/limits for precise GPU allocation
- Can request exactly 1 GPU per pod

**Configuration**:
- Use: `amd-gpu-kyverno-policy.yaml`
- Install an AMD GPU device plugin first
- Policy will inject GPU resource requests/limits
- Kubernetes scheduler handles allocation

**Pros**:
- Kubernetes-native GPU resource management
- Automatic GPU allocation and isolation
- Better resource tracking

**Cons**:
- Requires device plugin installation
- More complex setup
- AMD device plugins less standardized than NVIDIA

## Recommended Next Steps

### Option A: Install Device Plugin (Recommended)

1. **Install the official AMD GPU device plugin**:
   ```bash
   cd discord-cluster-manager/k8s
   ./install-amd-gpu-device-plugin.sh
   ```
   
   Or manually:
   ```bash
   kubectl create -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-dp.yaml
   ```

2. **Verify GPU resources are exposed**:
   ```bash
   kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:"status.capacity.amd\.com/gpu"
   ```

3. **Use the full policy with resource requests/limits**:
   ```bash
   kubectl apply -f k8s/amd-gpu-kyverno-policy.yaml
   ```

4. **Label your GPU node**:
   ```bash
   kubectl label nodes <node-name> amd.com/gpu.present=true
   ```

### Option B: Without Device Plugin (Simpler, but less precise)

1. **Use the no-device-plugin policy**:
   ```bash
   kubectl apply -f k8s/amd-gpu-kyverno-policy-no-device-plugin.yaml
   ```

2. **Label your GPU node**:
   ```bash
   kubectl label nodes rocm-7-1-software-gpu-mi300x1-192gb-devcloud-atl1 amd.com/gpu.present=true
   ```

3. **Configure ARC with max runners** to limit concurrent pods:
   - Set max runners to 1 (for 1 GPU) or 8 (for 8 GPUs)
   - This prevents too many pods from running simultaneously

4. **In your workflow/container**, use environment variables to select GPU:
   - `ROCR_VISIBLE_DEVICES=0` for first GPU
   - `ROCR_VISIBLE_DEVICES=1` for second GPU
   - etc.

## Future: Installing GPU Device Plugin

If you want to install a GPU device plugin later:

1. **Research AMD GPU device plugins**:
   - Look for official AMD/ROCm device plugins
   - Or community-maintained plugins
   - Or create a custom device plugin

2. **After installation**, switch to the full policy:
   ```bash
   kubectl delete clusterpolicy inject-amd-gpu-node-selector
   kubectl apply -f k8s/amd-gpu-kyverno-policy.yaml
   ```

## Checking GPU Resources

To verify GPU resources are available:
```bash
kubectl describe node <node-name> | grep -i gpu
kubectl get node <node-name> -o json | jq '.status.capacity | keys'
```

If you see GPU resources listed, you can use the full policy with resource requests/limits.

