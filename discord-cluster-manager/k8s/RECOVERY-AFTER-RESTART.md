# Recovery Guide After Server Restart

This guide helps you recover your AMD ARC setup after a server restart.

## What Persists Automatically

After a restart, the following should automatically recover:

1. **k3s Kubernetes cluster** - If k3s is installed as a system service, it will start automatically
2. **Helm releases** - All Helm installations (ARC, Kyverno) are stored in Kubernetes and will persist
3. **AMD GPU Device Plugin** - DaemonSet will restart automatically
4. **ARC Runner Scale Set** - The AutoscalingRunnerSet resource persists in Kubernetes

## What Needs to Be Reapplied

The following need to be reapplied after a restart (they are stored in the repo but not in Kubernetes):

1. **Kyverno GPU Policy** - The ClusterPolicy needs to be reapplied

## Step-by-Step Recovery

### 1. Verify k3s is Running

```bash
# Check k3s service status
sudo systemctl status k3s

# If not running, start it
sudo systemctl start k3s

# Verify kubectl works
export KUBECONFIG=~/.kube/config
kubectl get nodes
```

### 2. Verify All Components Are Running

```bash
export KUBECONFIG=~/.kube/config

# Check nodes
kubectl get nodes

# Check ARC system components
kubectl get pods -n arc-systems

# Check Kyverno
kubectl get pods -n kyverno

# Check AMD GPU device plugin
kubectl get pods -n kube-system | grep amdgpu

# Check ARC runner scale set
kubectl get autoscalingrunnersets -n arc-runners
```

### 3. Reapply Kyverno Policy

```bash
export KUBECONFIG=~/.kube/config
cd /path/to/ttt-continuous-runner-public/discord-cluster-manager/k8s
kubectl apply -f amd-gpu-kyverno-policy.yaml
```

### 4. Verify GPU Resources

```bash
export KUBECONFIG=~/.kube/config

# Check GPU resources on node
kubectl describe node | grep -A 5 "amd.com/gpu"

# Verify Kyverno policy is applied
kubectl get clusterpolicy inject-amd-gpu-resources -o yaml

# Test that policy works
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: test-recovery-workflow
  namespace: arc-runners
spec:
  containers:
    - name: test
      image: ghcr.io/leoxinhaolee/amd-runner:latest
      command: ["sh", "-c", "ls -la /dev/kfd /dev/dri/renderD* 2>&1 | head -5 && python3 -c 'import torch; print(\"CUDA available:\", torch.cuda.is_available())' 2>&1"]
EOF

sleep 8
kubectl logs test-recovery-workflow -n arc-runners
kubectl delete pod test-recovery-workflow -n arc-runners
```

## Quick Recovery Script

Save this as `recover-amd-arc.sh`:

```bash
#!/bin/bash
set -e

export KUBECONFIG=~/.kube/config

echo "=== Step 1: Checking k3s ==="
if ! systemctl is-active --quiet k3s; then
    echo "k3s is not running. Starting..."
    sudo systemctl start k3s
    sleep 5
fi

echo "=== Step 2: Verifying components ==="
kubectl get nodes
kubectl get pods -n arc-systems
kubectl get pods -n kyverno | grep -v Completed
kubectl get pods -n kube-system | grep amdgpu
kubectl get autoscalingrunnersets -n arc-runners

echo "=== Step 3: Reapplying Kyverno policy ==="
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
kubectl apply -f "${SCRIPT_DIR}/amd-gpu-kyverno-policy.yaml"

echo "=== Step 4: Verifying GPU resources ==="
kubectl describe node | grep -A 5 "amd.com/gpu"
kubectl get clusterpolicy inject-amd-gpu-resources

echo "=== Recovery complete! ==="
```

Make it executable and run:
```bash
chmod +x recover-amd-arc.sh
./recover-amd-arc.sh
```

## Troubleshooting

### k3s Not Starting

```bash
# Check k3s logs
sudo journalctl -u k3s -n 100

# Restart k3s
sudo systemctl restart k3s
```

### Components Not Running

```bash
# Check all pods status
kubectl get pods --all-namespaces

# Check for CrashLoopBackOff
kubectl get pods --all-namespaces | grep -v Running | grep -v Completed

# Check specific component logs
kubectl logs -n arc-systems <pod-name>
kubectl logs -n kyverno <pod-name>
```

### GPU Resources Not Showing

```bash
# Restart AMD GPU device plugin
kubectl rollout restart daemonset/amdgpu-device-plugin-daemonset -n kube-system

# Wait and check again
sleep 10
kubectl describe node | grep -A 5 "amd.com/gpu"
```

### ARC Not Working

```bash
# Check ARC runner set status
kubectl get autoscalingrunnersets -n arc-runners -o yaml

# Check for runner pods
kubectl get pods -n arc-runners

# Check ARC logs
kubectl logs -n arc-systems -l app.kubernetes.io/name=gha-runner-scale-set-controller
```

## Files to Keep Safe

These files in the repository contain the configuration:

- `discord-cluster-manager/k8s/amd-gpu-kyverno-policy.yaml` - The Kyverno policy (CRITICAL)
- `discord-cluster-manager/k8s/install-amd-arc.sh` - Installation script (for reference)
- `discord-cluster-manager/k8s/install-amd-gpu-device-plugin.sh` - Device plugin installer (for reference)

All other configuration is stored in Kubernetes and will persist automatically.

## Verification Checklist

After recovery, verify:

- [ ] k3s is running: `sudo systemctl status k3s`
- [ ] Nodes are ready: `kubectl get nodes`
- [ ] ARC controller pods running: `kubectl get pods -n arc-systems`
- [ ] Kyverno pods running: `kubectl get pods -n kyverno`
- [ ] AMD GPU device plugin running: `kubectl get pods -n kube-system | grep amdgpu`
- [ ] GPU resources visible: `kubectl describe node | grep amd.com/gpu`
- [ ] Kyverno policy applied: `kubectl get clusterpolicy inject-amd-gpu-resources`
- [ ] ARC runner set exists: `kubectl get autoscalingrunnersets -n arc-runners`
- [ ] Test pod can access GPU: Run the test pod command above


