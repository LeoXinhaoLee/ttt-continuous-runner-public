# AMD GPU ARC Setup with Actions Runner Controller

This guide walks through setup of the Actions Runner Controller (ARC) for GitHub Actions with AMD GPUs (ROCm), configured for scalable GPU execution.

## Prerequisites

1. **Kubernetes Cluster**: A working Kubernetes cluster with at least 1 node
   - See `KUBERNETES-SETUP.md` for installation instructions
   - Recommended: k3s for single-node setups
2. **AMD GPU Drivers & ROCm**: ROCm drivers installed on nodes with AMD GPUs
3. **AMD GPU Device Plugin** (optional): For automatic GPU discovery, or manual node labeling
4. **kubectl**: Installed and configured for your cluster
   - Usually included with Kubernetes installation
5. **Helm**: Installed and up-to-date
   - Install: `curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash`
6. **GitHub Personal Access Token (PAT)**: Required for authenticating with GitHub

## Current Configuration

- **Starting Setup**: 1 node, 1 GPU (for debugging)
- **Target**: 1 node, 8 GPUs → 2 nodes, 16 GPUs

---

## Installation Steps

### 1. Clone the Actions Runner Controller Repository (if needed)

```bash
# Only if you need the charts locally
git clone https://github.com/actions/actions-runner-controller.git
```

### 2. Install Local-Path Provisioner

The local-path provisioner is required for creating Persistent Volume Claims (PVCs) for pods.

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml
```

### 3. Install Kyverno

Kyverno is used for mutating admission webhooks to handle GPU-specific resource assignments.

```bash
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update
helm install kyverno kyverno/kyverno -n kyverno --create-namespace
```

### 4. Label GPU Nodes

Label nodes that have AMD GPUs. Replace `<node-name>` with your actual node name.

```bash
# Label the node to indicate it has AMD GPUs
kubectl label nodes <node-name> amd.com/gpu.present=true

# Verify the label
kubectl get nodes --show-labels | grep amd.com/gpu.present
```

**Note**: AMD GPU device plugin is less standardized than NVIDIA. You may need to:
- Manually label nodes (as above)
- Or use a custom device plugin that exposes GPU resources
- The exact resource name may vary; adjust the Kyverno policy accordingly

### 5. Install Runner Scale Set Controller

```bash
NAMESPACE="arc-systems"
helm install arc \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller
```

### 6. Create GitHub PAT Secret

```bash
NAMESPACE="arc-runners"
GITHUB_PAT="ghp_YOUR_TOKEN_HERE"  # Replace with your actual PAT

kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic github-pat-secret \
    --namespace "${NAMESPACE}" \
    --from-literal=github_token="${GITHUB_PAT}" \
    --dry-run=client -o yaml | kubectl apply -f -
```

### 7. Install and Configure Runner Set

Install the runner scale set using Helm. Update the GitHub repository URL:

```bash
INSTALLATION_NAME="amd-arc-runner"
NAMESPACE="arc-runners"
GITHUB_CONFIG_URL="https://github.com/LeoXinhaoLee/ttt-continuous-runner-public"  # Change to your repo
GITHUB_PAT="ghp_YOUR_TOKEN_HERE"  # Replace with your actual PAT

helm install "${INSTALLATION_NAME}" \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    --set githubConfigUrl="${GITHUB_CONFIG_URL}" \
    --set githubConfigSecret.github_token="${GITHUB_PAT}" \
    --set containerMode.type="kubernetes" \
    --set template.spec.containers[0].image="ghcr.io/actions/actions-runner:latest" \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
```

### 8. Determine GPU Resource Name

**IMPORTANT**: AMD GPU device plugins are less standardized than NVIDIA. Before proceeding, check what GPU resource name your setup uses:

```bash
kubectl describe node <node-name> | grep -i gpu
```

Look for resource names like:
- `amd.com/gpu`
- `rocm/gpu`
- `amd.com/rocm`
- Or a custom name from your device plugin

**Note**: If you don't have a device plugin, you may need to manually manage GPU allocation or install an AMD GPU device plugin. The configuration below uses `amd.com/gpu` as a default - you'll need to adjust if your setup uses a different name.

### 9. Check GPU Resources

**Important**: Check if GPU resources are available in Kubernetes:

```bash
cd discord-cluster-manager/k8s
./check-gpu-resources.sh
```

**Two scenarios**:

#### Scenario A: GPU Resources Available (Device Plugin Installed)

If you see GPU resources (e.g., `amd.com/gpu`, `rocm/gpu`) in the output, use the full policy:

```bash
kubectl apply -f k8s/amd-gpu-kyverno-policy.yaml
```

**Before applying**, if your GPU resource name is different from `amd.com/gpu`, edit the file and replace all occurrences with your resource name.

#### Scenario B: No GPU Resources (No Device Plugin)

If no GPU resources are found, use the simpler policy that only uses node selectors:

```bash
kubectl apply -f k8s/amd-gpu-kyverno-policy-no-device-plugin.yaml
```

This policy schedules pods on GPU nodes but doesn't use resource requests/limits. You'll need to limit concurrent pods via ARC configuration instead.

See `GPU-SETUP-NOTES.md` for more details.

Or apply directly:

```bash
NAMESPACE="arc-runners"
cat <<EOF | kubectl apply -f -
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: inject-amd-gpu-resources
spec:
  rules:
    - name: add-amd-gpu-resources
      match:
        resources:
          kinds:
            - Pod
          namespaces:
            - ${NAMESPACE}
      mutate:
        patchStrategicMerge:
          spec:
            containers:
              - (name): "*"
                resources:
                  requests:
                    amd.com/gpu: "1"
                  limits:
                    amd.com/gpu: "1"
                securityContext:
                  capabilities:
                    add:
                      - SYS_ADMIN
                      - SYS_RESOURCE
                      - SYS_PTRACE
            nodeSelector:
              amd.com/gpu.present: "true"
EOF
```

**Important**: The resource name `amd.com/gpu` may need to be adjusted based on your device plugin. Common alternatives:
- `rocm/gpu` 
- `amd.com/rocm`
- Or a custom resource name from your device plugin

### 10. Set Default Limits/Requests for Namespace (Only if GPU Device Plugin is Installed)

**Skip this step** if you're using `amd-gpu-kyverno-policy-no-device-plugin.yaml` (no device plugin).

Only apply this if GPU resources are available in Kubernetes:

```bash
kubectl apply -f k8s/amd-gpu-limitrange.yaml
```

**Note**: Update the resource name in this file if different from `amd.com/gpu`.

Or apply directly:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: LimitRange
metadata:
  name: amd-gpu-limits
  namespace: arc-runners
spec:
  limits:
    - default:
        amd.com/gpu: "1"
      defaultRequest:
        amd.com/gpu: "1"
      type: Container
EOF
```

### 11. Update Workflow to Use ARC Runner Label

Update your workflow to use the runner label. The runner label is typically generated from the installation name. Check the runner label:

```bash
kubectl get runnerscalesets -n arc-runners -o yaml | grep runnerLabel
```

Then update `.github/workflows/amd-mla-decode-workflow.yml`:

```yaml
jobs:
  run:
    runs-on: <runner-label-from-arc>  # Get with: kubectl get autoscalingrunnersets -n arc-runners -o jsonpath='{.items[0].status.runnerLabel}'
```

---

## Scaling Configuration

### Current: 1 Node, 1 GPU

The setup above is configured for 1 GPU per pod. With 1 node having 1 GPU, you can run 1 concurrent job.

### Scaling to 1 Node, 8 GPUs

1. Ensure your node has 8 GPUs available
2. No changes needed to ARC configuration - it will automatically create up to 8 pods (1 per GPU)
3. Verify GPU availability:
   ```bash
   kubectl describe node <node-name> | grep amd.com/gpu
   ```

### Scaling to 2-4 Nodes (Multiple GPUs)

#### Step 1: Add Nodes to Kubernetes Cluster

If using k3s, add agent nodes:
```bash
# On each new node
K3S_TOKEN=<token-from-server> \
K3S_URL=https://<server-ip>:6443 \
curl -sfL https://get.k3s.io | sh -
```

#### Step 2: Label All GPU Nodes

Label each node that has GPUs:
```bash
kubectl label nodes <node-1-name> amd.com/gpu.present=true
kubectl label nodes <node-2-name> amd.com/gpu.present=true
kubectl label nodes <node-3-name> amd.com/gpu.present=true
# ... and so on
```

Verify labels:
```bash
kubectl get nodes --show-labels | grep amd.com/gpu.present
```

#### Step 3: Verify Node Setup

```bash
# Check all nodes
kubectl get nodes

# Check GPU resources on each node (if device plugin is installed)
kubectl describe node <node-name> | grep -i gpu
```

#### Step 4: ARC Auto-Scaling

**No code changes needed!** ARC and Kubernetes will automatically:
- Create pods on-demand as jobs arrive
- Schedule pods to nodes with available GPUs
- Distribute workload across all labeled nodes
- Respect the 1 GPU per pod limit

**Example: 2 nodes with 8 GPUs each = 16 total GPUs**
- ARC can run up to 16 concurrent jobs
- Kubernetes scheduler distributes pods across both nodes
- Each pod gets exactly 1 GPU

#### Step 5: Monitor Distribution

```bash
# Watch pods being distributed across nodes
kubectl get pods -n arc-runners -o wide

# Check which node each pod is running on
kubectl get pods -n arc-runners -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,STATUS:.status.phase
```

---

## Validation

### Check Runner Scale Set Status

```bash
kubectl get autoscalingrunnersets -n arc-runners
kubectl describe autoscalingrunnersets -n arc-runners
```

### Check Runner Pods

```bash
kubectl get pods -n arc-runners
```

### Test GPU Allocation

Create a test pod to verify GPU resource allocation:

```bash
kubectl apply -f k8s/amd-gpu-test-pod.yaml
kubectl describe pod -n arc-runners amd-gpu-test-pod
kubectl delete pod -n arc-runners amd-gpu-test-pod
```

---

## Troubleshooting

### Pods Not Getting GPUs

1. Check node labels:
   ```bash
   kubectl get nodes --show-labels | grep amd
   ```

2. Check GPU resources on node:
   ```bash
   kubectl describe node <node-name> | grep -i gpu
   ```

3. Check Kyverno policy:
   ```bash
   kubectl get clusterpolicy inject-amd-gpu-resources -o yaml
   ```

### Runner Pods Not Starting

1. Check runner scale set status:
   ```bash
   kubectl describe autoscalingrunnersets -n arc-runners
   ```

2. Check pod events:
   ```bash
   kubectl get events -n arc-runners --sort-by='.lastTimestamp'
   ```

### GPU Resource Name Issues

If `amd.com/gpu` doesn't work, you may need to:
1. Check what resource name your device plugin uses
2. Update the Kyverno policy with the correct resource name
3. Update the LimitRange accordingly

---

## Notes

- **Container Image**: The workflow uses `ghcr.io/leoxinhaolee/amd-runner:latest` which includes ROCm
- **Privileged Mode**: The workflow uses `--privileged` flag for GPU access
- **ROCm Access**: Ensure nodes have ROCm drivers and proper permissions for GPU access

---

## Uninstalling

To remove ARC:

```bash
helm uninstall "${INSTALLATION_NAME}" --namespace "${NAMESPACE}"
helm uninstall arc --namespace arc-systems
helm uninstall kyverno --namespace kyverno
```

