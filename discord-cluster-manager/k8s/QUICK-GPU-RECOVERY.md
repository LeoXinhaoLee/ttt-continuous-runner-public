# Quick GPU Hang Recovery

If `amd-smi` hangs, the GPU driver is stuck at the kernel level. Try these steps in order:

## Option 1: Restart GPU Device Plugin (Quickest)

```bash
export KUBECONFIG=~/.kube/config
kubectl rollout restart daemonset/amdgpu-device-plugin-daemonset -n kube-system
sleep 10
kubectl rollout status daemonset/amdgpu-device-plugin-daemonset -n kube-system
```

Then try `amd-smi` again.

## Option 2: Restart k3s (Most Likely to Work)

```bash
sudo systemctl restart k3s
sleep 15
export KUBECONFIG=~/.kube/config
kubectl get nodes

# Reapply Kyverno policy
cd /home/runner/ttt-continuous-runner-public/discord-cluster-manager/k8s
kubectl apply -f amd-gpu-kyverno-policy.yaml
```

Then try `amd-smi` again.

## Option 3: Reboot Server (Last Resort)

```bash
sudo reboot
```

After reboot, run:
```bash
cd /home/runner/ttt-continuous-runner-public/discord-cluster-manager/k8s
./recover-amd-arc.sh
```

## Test GPU Recovery

After recovery, test GPU access:

```bash
# Quick test
rocminfo | head -20

# Or
amd-smi
```

