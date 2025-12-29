# k3s + ROCm GPU Hang Fix

## Problem

k3s uses containerd + runc with different LSM/seccomp/AppArmor defaults than Docker. This causes GPU hangs and `/dev/kfd` access errors in ROCm workloads, even with `privileged: true`.

## Solution

The Kyverno policy now includes:

1. **seccomp unconfined**: Explicitly disables seccomp profile
2. **Large /dev/shm (8Gi)**: PyTorch/ROCm stacks need more shared memory than default
3. **Privileged mode**: Still required for device access

## AppArmor Note

AppArmor annotations are per-container and require knowing the container name, which makes them difficult to inject via Kyverno for dynamic ARC workflow pods.

If you still experience GPU hangs after these fixes, disable AppArmor at the k3s level:

### Option 1: Start k3s with AppArmor disabled

Add flag when starting k3s (if you control the launch)

### Option 2: Customize k3s containerd config

Edit `/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl` to disable AppArmor, then restart k3s.

## Testing

Use `test-rocm-k3s.yaml` to verify the fix works with a plain pod before testing with ARC workflow pods.

