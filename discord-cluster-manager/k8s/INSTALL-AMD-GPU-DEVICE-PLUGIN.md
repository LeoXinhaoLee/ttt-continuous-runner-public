# Installing AMD GPU Device Plugin for Kubernetes

AMD has an official GPU device plugin for Kubernetes that exposes AMD GPUs as schedulable resources.

## Option 1: Official AMD GPU Device Plugin (Recommended)

### Simple Installation

The official AMD GPU device plugin can be installed with a single command:

```bash
kubectl create -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-dp.yaml
```

**Note**: This command does **NOT** require root/sudo. You just need:
- `kubectl` installed
- Kubeconfig properly configured (see k3s setup docs)

The device plugin DaemonSet will run as privileged containers, but that's handled by Kubernetes itself - you don't need root to create the resources.

### Verify Installation

Check if GPUs are now exposed as resources:

```bash
# Check node capacity for GPU resources
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:"status.capacity.amd\.com/gpu"

# Or check detailed node info
kubectl describe node <node-name> | grep -i "amd.com/gpu"

# Check node capacity JSON
kubectl get node <node-name> -o json | jq '.status.capacity."amd.com/gpu"'
```

You should see GPU resources like:
```
NAME                                                  GPU
rocm-7-1-software-gpu-mi300x1-192gb-devcloud-atl1   1
```

### Check Device Plugin Pods

```bash
# Check if device plugin pods are running
kubectl get pods -n kube-system | grep amd-gpu

# Check logs if needed
kubectl logs -n kube-system -l name=amd-gpu-device-plugin
```

### Resource Name

The device plugin exposes GPUs as: **`amd.com/gpu`**

This matches our Kyverno policy configuration! If you see this resource, you can use:
- `k8s/amd-gpu-kyverno-policy.yaml` (with resource requests/limits)

---

## Option 2: AMD GPU Operator (Advanced)

For enhanced management, monitoring, and automatic driver installation, you can use the AMD GPU Operator:

### Prerequisites

1. **Install cert-manager**:
```bash
helm repo add jetstack https://charts.jetstack.io --force-update
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.15.1 \
  --set crds.enabled=true
```

2. **Add ROCm Helm Repository**:
```bash
helm repo add rocm https://rocm.github.io/gpu-operator
helm repo update
```

3. **Install AMD GPU Operator**:
```bash
helm install amd-gpu-operator rocm/gpu-operator-charts \
  --namespace kube-amd-gpu \
  --create-namespace \
  --version v1.2.2
```

The GPU Operator includes the device plugin and additional management features.

---

## Option 3: Community/Alternative Device Plugins

### k8s-device-plugin (Community Fork)

There's a community fork of NVIDIA's k8s-device-plugin adapted for AMD GPUs:

**Repository**: Check for `k8s-device-plugin` forks supporting AMD/ROCm

**Status**: May not be actively maintained, check GitHub for latest status

**Installation** (if available):
```bash
# Clone the repository
git clone https://github.com/<fork-repo>/k8s-device-plugin.git
cd k8s-device-plugin

# Build and deploy (instructions vary by fork)
kubectl apply -f deployments/amd/
```

---

## Option 2: Custom Device Plugin (Recommended)

Since AMD device plugins are less standardized, creating a custom device plugin may be the most reliable approach.

### Simple Custom Device Plugin Script

Create a DaemonSet that exposes GPU resources based on actual GPUs on the node:

```bash
# Create a simple device plugin that detects AMD GPUs
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: amd-gpu-device-plugin
  namespace: kube-system
spec:
  selector:
    matchLabels:
      name: amd-gpu-device-plugin
  template:
    metadata:
      labels:
        name: amd-gpu-device-plugin
    spec:
      hostNetwork: true
      containers:
      - image: nvidia/k8s-device-plugin:latest  # Placeholder - you'd need an AMD-compatible image
        name: amd-gpu-device-plugin
        securityContext:
          privileged: true
        volumeMounts:
        - name: device-plugin
          mountPath: /var/lib/kubelet/device-plugins
        env:
        - name: GPU_RESOURCE_NAME
          value: "amd.com/gpu"
        - name: NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
      volumes:
      - name: device-plugin
        hostPath:
          path: /var/lib/kubelet/device-plugins
      nodeSelector:
        amd.com/gpu.present: "true"
EOF
```

**Note**: This is a template - you'd need to adapt it based on actual AMD GPU device plugin implementations.

---

## Option 3: Node Feature Discovery + Manual Resource Annotation

Use Node Feature Discovery (NFD) to detect GPUs and manually annotate nodes with GPU resources.

### Install Node Feature Discovery

```bash
# Install NFD
kubectl apply -k https://github.com/kubernetes-sigs/node-feature-discovery/deployment/overlays/default?ref=v0.15.4
```

### Manually Annotate Nodes with GPU Resources

After detecting GPUs with NFD, you can manually patch nodes to expose GPU resources:

```bash
# Count GPUs on node (run on the node itself)
GPU_COUNT=$(rocm-smi -L | wc -l)

# Patch node to add GPU resources
kubectl patch node <node-name> -p '{"status":{"capacity":{"amd.com/gpu":"'${GPU_COUNT}'"}}}'
kubectl patch node <node-name> -p '{"status":{"allocatable":{"amd.com/gpu":"'${GPU_COUNT}'"}}}'
```

**Limitation**: These patches are temporary and will be reset by kubelet. You'd need a controller to maintain them.

---

## Option 4: Use Node Labels Only (Current Recommended Approach)

**For now, the recommended approach is to proceed WITHOUT a device plugin** and use:

1. **Node labels** to schedule pods on GPU nodes
2. **ARC max runners** to limit concurrent pods
3. **Container-level GPU selection** (ROCR_VISIBLE_DEVICES)

This is simpler and works immediately without additional components.

---

## Option 5: Check for Official AMD/ROCm Device Plugin

Check if AMD has released an official device plugin:

1. **ROCm Documentation**: Check AMD's official ROCm documentation
2. **AMD GitHub**: Search for device-plugin repositories
3. **Kubernetes SIG**: Check Kubernetes special interest groups

---

## Testing Device Plugin Installation

After installing a device plugin, verify GPU resources are exposed:

```bash
# Check node resources
kubectl describe node <node-name> | grep -i gpu

# Check node capacity
kubectl get node <node-name> -o json | jq '.status.capacity'

# Should see something like:
# "amd.com/gpu": "1"  (or "8" if you have 8 GPUs)
```

---

## Recommendation

**For your use case (1-4 nodes, starting with 1 node/1 GPU):**

1. **Install the official AMD GPU device plugin** (Option 1) - it's simple and works well
2. **Verify GPU resources are exposed** using the verification commands above
3. **Use the full Kyverno policy** (`amd-gpu-kyverno-policy.yaml`) with resource requests/limits
4. **Label your nodes** with `amd.com/gpu.present=true`

This gives you proper Kubernetes-level GPU resource management.

**Alternative**: If you prefer to start simple, you can use the node-selector-only approach first and install the device plugin later.

---

## Resources

- NVIDIA k8s-device-plugin (reference implementation): https://github.com/NVIDIA/k8s-device-plugin
- Node Feature Discovery: https://github.com/kubernetes-sigs/node-feature-discovery
- ROCm Documentation: https://rocm.docs.amd.com/
- Kubernetes Device Plugins: https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/

---

## If You Find a Working Solution

If you discover or implement a working AMD GPU device plugin, please:

1. Document the installation steps
2. Note the resource name it uses (e.g., `amd.com/gpu`, `rocm/gpu`)
3. Update the Kyverno policy files accordingly
4. Update this documentation

