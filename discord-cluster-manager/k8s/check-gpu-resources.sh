#!/bin/bash
#
# Script to check GPU resources available on Kubernetes nodes
# This helps determine the correct GPU resource name for AMD GPUs

set -e

echo "Checking GPU resources on Kubernetes nodes..."
echo ""

# Set KUBECONFIG if ~/.kube/config exists but KUBECONFIG is not set
if [ -f ~/.kube/config ] && [ -z "$KUBECONFIG" ]; then
    export KUBECONFIG=~/.kube/config
    echo "Using kubeconfig from: ~/.kube/config"
    echo ""
fi

# Determine kubectl command to use
if kubectl get nodes &>/dev/null 2>&1; then
    KUBECTL_CMD="kubectl"
elif sudo k3s kubectl get nodes &>/dev/null 2>&1; then
    KUBECTL_CMD="sudo k3s kubectl"
    echo "Using: sudo k3s kubectl (kubeconfig not accessible)"
    echo ""
else
    echo "Error: Cannot connect to cluster."
    echo ""
    if [ -f ~/.kube/config ]; then
        echo "Kubeconfig file exists at ~/.kube/config but kubectl cannot use it."
        echo "Try: export KUBECONFIG=~/.kube/config"
    else
        echo "Please set up kubeconfig first:"
        echo "  mkdir -p ~/.kube"
        echo "  sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config"
        echo "  sudo chown \$USER:\$USER ~/.kube/config"
        echo "  export KUBECONFIG=~/.kube/config"
    fi
    exit 1
fi

# Get all nodes
NODES=$($KUBECTL_CMD get nodes -o name 2>/dev/null)

if [ -z "$NODES" ]; then
    echo "Error: No nodes found. Check your kubectl configuration."
    exit 1
fi

for NODE in $NODES; do
    NODE_NAME=${NODE#node/}
    echo "=========================================="
    echo "Node: $NODE_NAME"
    echo "=========================================="
    
    # Check node labels for GPU-related labels
    echo ""
    echo "GPU-related labels:"
    $KUBECTL_CMD get node "$NODE_NAME" --show-labels 2>/dev/null | grep -iE "(gpu|amd|rocm|device)" || echo "  (no GPU-related labels found)"
    
    # Check node capacity and allocatable resources
    echo ""
    echo "GPU resources in node capacity/allocatable:"
    $KUBECTL_CMD describe node "$NODE_NAME" 2>/dev/null | grep -iE "(gpu|amd|rocm)" | head -20 || echo "  (no GPU resources found in capacity)"
    
    # Check node status for device plugin resources
    echo ""
    echo "Full resource list (looking for GPU resources):"
    if command -v jq &> /dev/null; then
        $KUBECTL_CMD get node "$NODE_NAME" -o json 2>/dev/null | jq -r '.status.capacity | to_entries[] | select(.key | test("(?i)(gpu|amd|rocm|device)")) | "  \(.key): \(.value)"' || \
        echo "  (no GPU resources found or jq parsing failed)"
    else
        # Fallback without jq
        $KUBECTL_CMD get node "$NODE_NAME" -o jsonpath='{.status.capacity}' 2>/dev/null | grep -iE "(gpu|amd|rocm)" || echo "  (no GPU resources found - install jq for better output)"
    fi
    
    echo ""
done

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo ""
echo "Look for resource names like:"
echo "  - amd.com/gpu"
echo "  - rocm/gpu"
echo "  - amd.com/rocm"
echo "  - Or other GPU-related resource names"
echo ""
echo "If you see a GPU resource name, update the YAML files:"
echo "  - k8s/amd-gpu-kyverno-policy.yaml"
echo "  - k8s/amd-gpu-limitrange.yaml"
echo ""
echo "Replace 'amd.com/gpu' with the actual resource name found above."

