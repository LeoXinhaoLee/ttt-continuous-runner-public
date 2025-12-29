# Kubernetes Setup Guide for AMD GPU ARC

This guide covers different options for setting up Kubernetes, depending on your use case.

## Quick Decision Guide

- **Local testing/development**: Use **k3s** or **microk8s** (easiest)
- **Single-node production**: Use **k3s** or **microk8s**
- **Multi-node production**: Use **kubeadm** or managed Kubernetes (EKS, GKE, AKS)

---

## Option 1: k3s (Recommended for 1-4 Nodes)

k3s is lightweight, easy to install, and supports multi-node clusters. Great for 1-4 nodes.

**Permissions**: Installation requires `sudo`/root, but you can use kubectl as a regular user after setup. See `k3s-permissions.md` for details.

### Single Node Installation

**Note**: k3s installation requires `sudo`/root access. Once installed, you can use kubectl as a regular user.

```bash
# Install k3s on a single node (requires sudo)
curl -sfL https://get.k3s.io | sh -

# Verify installation (can use sudo k3s kubectl or regular kubectl)
sudo k3s kubectl get nodes

# Set up kubectl for regular user (copy kubeconfig)
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
export KUBECONFIG=~/.kube/config

# Now you can use kubectl as regular user (no sudo needed)
kubectl get nodes
```

**Root requirements:**
- **Installation**: Requires `sudo`/root (installs systemd services, system binaries)
- **Usage**: No root needed after installation if kubeconfig is set up
- **Service management**: Requires `sudo` (e.g., `sudo systemctl restart k3s`)

### Multi-Node Setup (2-4 Nodes)

k3s supports multi-node clusters with a server (master) and agent nodes.

#### Step 1: Install Server Node (First Node)

**Note**: Installation requires `sudo`/root. After setup, you can use kubectl as a regular user.

```bash
# On the first node (will be the server/master)
# Requires sudo for installation
curl -sfL https://get.k3s.io | sh -

# Get the node token (needed for agent nodes) - requires sudo
sudo cat /var/lib/rancher/k3s/server/node-token

# Get the server IP address (no sudo needed)
hostname -I | awk '{print $1}'
# Or: ip addr show | grep "inet " | grep -v 127.0.0.1

# Set up kubectl on the server (copy config as regular user)
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
export KUBECONFIG=~/.kube/config

# Now use kubectl as regular user (no sudo needed)
kubectl get nodes
```

**Save these values:**
- `K3S_TOKEN`: The node token from `/var/lib/rancher/k3s/server/node-token`
- `K3S_URL`: The server IP address (e.g., `https://192.168.1.100:6443`)

#### Step 2: Install Agent Nodes (Additional Nodes)

On each additional node (node 2, 3, 4, etc.):

**Note**: Installation requires `sudo`/root. After installation, kubectl works as regular user.

```bash
# Install k3s as agent (replace with your values)
# Requires sudo for installation
K3S_TOKEN=<token-from-server> \
K3S_URL=https://<server-ip>:6443 \
curl -sfL https://get.k3s.io | sh -

# Verify agent is running (requires sudo for systemctl)
sudo systemctl status k3s-agent

# Note: On agent nodes, kubectl commands should be run from the server node
# Or copy kubeconfig from server to agent nodes if you want kubectl there
```

**Example:**
```bash
# If server IP is 192.168.1.100 and token is K10abc123...
K3S_TOKEN=K10abc123def456ghi789 \
K3S_URL=https://192.168.1.100:6443 \
curl -sfL https://get.k3s.io | sh -
```

#### Step 3: Verify Multi-Node Cluster

On the server node:

```bash
# Check all nodes
kubectl get nodes

# You should see all nodes (server + agents)
# Example output:
# NAME           STATUS   ROLES                  AGE   VERSION
# server-node    Ready    control-plane,master   5m    v1.28.x+k3s1
# agent-node-1   Ready    <none>                 2m    v1.28.x+k3s1
# agent-node-2   Ready    <none>                 1m    v1.28.x+k3s1
```

#### Step 4: Copy kubeconfig to Other Nodes (Optional)

If you want to run kubectl commands from agent nodes:

```bash
# On server, copy config
scp ~/.kube/config user@agent-node:~/.kube/config

# On agent node, update server IP in config if needed
# Edit ~/.kube/config and change the server URL to point to server IP
```

### Notes for GPU Support

- k3s runs as a systemd service (`k3s` on server, `k3s-agent` on agents)
- GPU access requires proper device permissions on each node
- Label each GPU node: `kubectl label nodes <node-name> amd.com/gpu.present=true`
- ARC will automatically distribute pods across all labeled nodes

### Networking Requirements

For multi-node k3s, ensure:
- All nodes can reach each other on port 6443 (API server)
- Firewall rules allow communication between nodes
- Nodes can resolve each other by hostname or IP

### Uninstall

**On server node:**
```bash
/usr/local/bin/k3s-uninstall.sh
```

**On agent nodes:**
```bash
/usr/local/bin/k3s-agent-uninstall.sh
```

---

## Option 2: microk8s (Ubuntu/Debian - Very Easy)

microk8s is great for Ubuntu/Debian systems and has built-in addons.

### Installation

```bash
# Install microk8s
sudo snap install microk8s --classic

# Add user to microk8s group
sudo usermod -a -G microk8s $USER
newgrp microk8s

# Enable required addons
microk8s enable dns storage

# Set up kubectl alias
sudo snap alias microk8s.kubectl kubectl

# Test
kubectl get nodes
```

### Notes for GPU Support

- microk8s has GPU support but may need additional configuration for AMD
- Check `microk8s enable gpu` (may not support AMD GPUs)

### Uninstall

```bash
sudo snap remove microk8s
```

---

## Option 3: minikube (Local Development)

Good for local testing but may have limitations with GPU passthrough.

### Installation

```bash
# Install minikube (adjust for your OS)
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# Start minikube
minikube start

# Use minikube's kubectl
minikube kubectl -- get nodes

# Or set up kubectl
minikube kubectl -- get nodes
```

### GPU Support

- GPU passthrough in minikube can be complex
- May not be ideal for AMD GPU workloads
- Better suited for CPU-only testing

---

## Option 4: kubeadm (Production Multi-Node)

For production deployments with multiple nodes.

### Installation on Ubuntu/Debian

```bash
# Install container runtime (containerd)
sudo apt-get update
sudo apt-get install -y containerd
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml
sudo systemctl restart containerd
sudo systemctl enable containerd

# Install kubeadm, kubelet, kubectl
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl

# Initialize control plane (on master node)
sudo kubeadm init --pod-network-cidr=10.244.0.0/16

# Set up kubectl
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Install network plugin (flannel example)
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

# Remove taint from master to allow pods (single-node setup)
kubectl taint nodes --all node-role.kubernetes.io/control-plane-
```

### Join Worker Nodes

```bash
# On worker nodes, run the join command from the master's kubeadm init output
sudo kubeadm join <master-ip>:6443 --token <token> --discovery-token-ca-cert-hash sha256:<hash>
```

---

## Option 5: Managed Kubernetes

Cloud providers offer managed Kubernetes:

- **AWS EKS**: `eksctl` tool
- **Google GKE**: `gcloud` CLI
- **Azure AKS**: `az` CLI

These handle cluster management but require cloud accounts.

---

## Post-Installation: GPU Support Setup

After installing Kubernetes, you need to set up GPU support for AMD:

### 1. Verify ROCm is Installed on Nodes

```bash
# On each node with GPUs
rocm-smi
# Should show GPU information
```

### 2. Install AMD GPU Device Plugin (Optional)

AMD GPU device plugins are less standardized. Options:

- **Manual labeling**: Label nodes and manually manage GPU allocation
- **Custom device plugin**: Use or create a device plugin that exposes GPU resources
- **Node Feature Discovery**: For automatic GPU detection

For now, you can proceed with manual node labeling (which our ARC setup uses).

### 3. Label GPU Nodes

```bash
kubectl label nodes <node-name> amd.com/gpu.present=true
```

### 4. Verify GPU Resources (if device plugin is installed)

```bash
kubectl describe node <node-name> | grep -i gpu
```

---

## Recommendation for Your Use Case

**For 1-4 nodes with AMD GPUs**: Use **k3s** (Recommended)

1. Simple installation (single command per node)
2. Lightweight and resource-efficient
3. Supports multi-node clusters (2-4 nodes)
4. Good for development and production
5. Easy to scale from 1 node to multiple nodes

**Quick Start:**
```bash
# Single node
curl -sfL https://get.k3s.io | sh -

# Multi-node: Install server first, then agents (see multi-node section above)
```

**Why k3s over other options:**
- **vs microk8s**: Better multi-node support, more widely used
- **vs minikube**: Real multi-node support (minikube is single-node only)
- **vs kubeadm**: Much simpler setup, less configuration needed
- **vs managed**: No cloud dependency, full control

Then proceed with the ARC setup as documented in `amd-arc-setup.md`.

---

## Troubleshooting

### kubectl not found

```bash
# For k3s
export KUBECONFIG=~/.kube/config
# Or use: sudo k3s kubectl

# For microk8s
sudo snap alias microk8s.kubectl kubectl
```

### Permission denied

```bash
# For k3s
sudo chown $USER ~/.kube/config

# For microk8s
sudo usermod -a -G microk8s $USER
newgrp microk8s
```

### Check cluster status

```bash
kubectl cluster-info
kubectl get nodes
kubectl get pods --all-namespaces
```

---

## Next Steps

After Kubernetes is installed:

1. Verify cluster: `kubectl get nodes`
2. Run GPU check: `./check-gpu-resources.sh`
3. Install ARC: Follow `amd-arc-setup.md` or use `install-amd-arc.sh`

