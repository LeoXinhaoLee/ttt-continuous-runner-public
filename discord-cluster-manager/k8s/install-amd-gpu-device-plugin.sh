#!/bin/bash
#
# Install AMD GPU Device Plugin for Kubernetes
# This installs the official ROCm k8s-device-plugin
#
# Note: This script does NOT require root/sudo. It uses kubectl which should
# work as a regular user if kubeconfig is set up properly.

set -e

echo "=========================================="
echo "Installing AMD GPU Device Plugin"
echo "=========================================="
echo ""

# Set KUBECONFIG if ~/.kube/config exists but KUBECONFIG is not set
if [ -f ~/.kube/config ] && [ -z "$KUBECONFIG" ]; then
    export KUBECONFIG=~/.kube/config
    echo "Using kubeconfig from: ~/.kube/config"
    echo ""
fi

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl is not installed or not in PATH"
    exit 1
fi

# Check if we can connect to cluster
if ! kubectl cluster-info &> /dev/null 2>&1; then
    echo "Error: Cannot connect to Kubernetes cluster"
    echo "Please check your kubectl configuration"
    echo ""
    echo "Make sure kubeconfig is set up:"
    echo "  export KUBECONFIG=~/.kube/config"
    echo ""
    echo "Or if using k3s:"
    echo "  mkdir -p ~/.kube"
    echo "  sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config"
    echo "  sudo chown \$USER:\$USER ~/.kube/config"
    exit 1
fi

echo "Installing AMD GPU Device Plugin..."
echo ""

# Install the device plugin
kubectl create -f https://raw.githubusercontent.com/ROCm/k8s-device-plugin/master/k8s-ds-amdgpu-dp.yaml

echo ""
echo "Waiting for device plugin pods to start..."
sleep 10

# Check device plugin pods
echo ""
echo "Checking device plugin pods..."
kubectl get pods -n kube-system | grep amd-gpu || echo "Device plugin pods not found (may still be starting)"

echo ""
echo "=========================================="
echo "Verification"
echo "=========================================="
echo ""
echo "Check if GPU resources are exposed on nodes:"
echo ""
echo "  kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:\"status.capacity.amd\\.com/gpu\""
echo ""
echo "Or check a specific node:"
echo "  kubectl describe node <node-name> | grep amd.com/gpu"
echo ""
echo "If you see GPU resources listed, you can now:"
echo "  1. Use the full Kyverno policy: amd-gpu-kyverno-policy.yaml"
echo "  2. Label nodes: kubectl label nodes <node-name> amd.com/gpu.present=true"
echo ""

