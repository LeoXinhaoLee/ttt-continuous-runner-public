# k3s Permissions and Root Requirements

## Quick Answer

- **Installation**: Requires `sudo`/root access
- **Usage (kubectl)**: No root needed after setup
- **Service management**: Requires `sudo`

## Detailed Requirements

### Installation (Requires Root/Sudo)

k3s installation requires root/sudo because it needs to:

1. **Install system binaries** to `/usr/local/bin/k3s`
2. **Create systemd services** (`k3s` on server, `k3s-agent` on agents)
3. **Create system directories** like `/var/lib/rancher/k3s/`
4. **Bind to privileged ports** (6443 for API server)
5. **Modify system files** and potentially firewall rules

**Installation command (requires sudo):**
```bash
curl -sfL https://get.k3s.io | sh -  # Runs with sudo internally
```

### Usage (No Root Needed After Setup)

Once k3s is installed, you can use kubectl as a **regular user**:

1. **Copy kubeconfig** (one-time setup, **REQUIRED**):
   ```bash
   mkdir -p ~/.kube
   sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
   sudo chown $USER:$USER ~/.kube/config
   chmod 600 ~/.kube/config
   export KUBECONFIG=~/.kube/config
   ```
   
   **Or use the helper script:**
   ```bash
   cd discord-cluster-manager/k8s
   ./fix-kubeconfig-permissions.sh
   ```
   
   **To make it permanent**, add to your shell profile:
   ```bash
   echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
   source ~/.bashrc
   ```

2. **Use kubectl without sudo**:
   ```bash
   kubectl get nodes           # No sudo needed
   kubectl get pods            # No sudo needed
   kubectl apply -f file.yaml  # No sudo needed
   ```

### Service Management (Requires Sudo)

Managing the k3s service requires sudo:

```bash
# Check status
sudo systemctl status k3s        # Server node
sudo systemctl status k3s-agent  # Agent nodes

# Start/stop/restart
sudo systemctl restart k3s
sudo systemctl stop k3s
sudo systemctl start k3s
```

### Security Considerations

k3s runs with root privileges, but:

- **kubectl access** is controlled by kubeconfig permissions
- **RBAC** (Role-Based Access Control) still applies for Kubernetes operations
- **User permissions** in Kubernetes are separate from system root access

### Alternative: Non-Root Installation (Advanced)

For non-root installations, you can use k3s in "rootless" mode, but it has limitations:

- More complex setup
- Some features may not work (e.g., LoadBalancer services)
- May have networking limitations
- Not recommended for production use

**Not recommended for your use case** (GPU workloads, ARC setup).

### Best Practice

1. **Install with sudo** (standard way, recommended)
2. **Set up kubeconfig** for regular user
3. **Use kubectl as regular user** for day-to-day operations
4. **Use sudo only when needed** for service management

### Example Workflow

```bash
# 1. Install (requires sudo - one time)
curl -sfL https://get.k3s.io | sh -

# 2. Set up kubeconfig (one time, uses sudo to copy)
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
export KUBECONFIG=~/.kube/config

# 3. Daily usage (no sudo needed)
kubectl get nodes
kubectl apply -f my-config.yaml
kubectl get pods -n arc-runners

# 4. Service management (only when needed, requires sudo)
sudo systemctl restart k3s
```

## Summary

| Operation | Root/Sudo Required? |
|-----------|---------------------|
| Installation | ✅ Yes |
| Using kubectl | ❌ No (after kubeconfig setup) |
| Service management | ✅ Yes |
| ARC setup/usage | ❌ No (kubectl commands) |

**Recommendation**: Install with sudo (it's the standard way), but set up kubeconfig so you can use kubectl as a regular user for your day-to-day work.

