#!/bin/bash
#
# Installation script for AMD GPU ARC setup
# Usage: ./install-amd-arc.sh [OPTIONS]
#
# This script sets up Actions Runner Controller (ARC) for AMD GPUs
# Starting configuration: 1 node, 1 GPU

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
NAMESPACE_ARC_SYSTEMS="arc-systems"
NAMESPACE_RUNNERS="arc-runners"
INSTALLATION_NAME="amd-arc-runner"
GITHUB_CONFIG_URL=""
GITHUB_PAT=""
NODE_NAME=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --github-url)
      GITHUB_CONFIG_URL="$2"
      shift 2
      ;;
    --github-pat)
      GITHUB_PAT="$2"
      shift 2
      ;;
    --node-name)
      NODE_NAME="$2"
      shift 2
      ;;
    --installation-name)
      INSTALLATION_NAME="$2"
      shift 2
      ;;
    --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --github-url URL          GitHub repository URL (required)"
      echo "  --github-pat TOKEN        GitHub Personal Access Token (required)"
      echo "  --node-name NAME          Kubernetes node name with AMD GPU (required)"
      echo "  --installation-name NAME  ARC installation name (default: amd-arc-runner)"
      echo "  --help                    Show this help message"
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      exit 1
      ;;
  esac
done

# Validate required arguments
if [ -z "$GITHUB_CONFIG_URL" ]; then
  echo -e "${RED}Error: --github-url is required${NC}"
  exit 1
fi

if [ -z "$GITHUB_PAT" ]; then
  echo -e "${RED}Error: --github-pat is required${NC}"
  exit 1
fi

if [ -z "$NODE_NAME" ]; then
  echo -e "${RED}Error: --node-name is required${NC}"
  exit 1
fi

# Check prerequisites
echo -e "${GREEN}Checking prerequisites...${NC}"

if ! command -v kubectl &> /dev/null; then
  echo -e "${RED}Error: kubectl is not installed${NC}"
  exit 1
fi

if ! command -v helm &> /dev/null; then
  echo -e "${RED}Error: helm is not installed${NC}"
  exit 1
fi

# Verify kubectl can connect to cluster
if ! kubectl cluster-info &> /dev/null; then
  echo -e "${RED}Error: Cannot connect to Kubernetes cluster${NC}"
  exit 1
fi

echo -e "${GREEN}Prerequisites check passed${NC}"
echo ""

# Step 1: Install Local-Path Provisioner
echo -e "${GREEN}Step 1: Installing Local-Path Provisioner...${NC}"
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml || echo -e "${YELLOW}Local-path provisioner may already be installed${NC}"
echo ""

# Step 2: Install Kyverno
echo -e "${GREEN}Step 2: Installing Kyverno...${NC}"
helm repo add kyverno https://kyverno.github.io/kyverno/ 2>/dev/null || true
helm repo update
helm install kyverno kyverno/kyverno -n kyverno --create-namespace 2>/dev/null || echo -e "${YELLOW}Kyverno may already be installed${NC}"
echo ""

# Step 3: Label GPU Node
echo -e "${GREEN}Step 3: Labeling GPU node...${NC}"
kubectl label nodes "${NODE_NAME}" amd.com/gpu.present=true --overwrite
echo "Labeled node: ${NODE_NAME}"
kubectl get nodes "${NODE_NAME}" --show-labels | grep amd.com/gpu.present
echo ""

# Step 4: Install ARC Controller
echo -e "${GREEN}Step 4: Installing ARC Controller...${NC}"
helm install arc \
    --namespace "${NAMESPACE_ARC_SYSTEMS}" \
    --create-namespace \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller \
    2>/dev/null || echo -e "${YELLOW}ARC controller may already be installed${NC}"
echo ""

# Step 5: Create GitHub PAT Secret
echo -e "${GREEN}Step 5: Creating GitHub PAT secret...${NC}"
kubectl create namespace "${NAMESPACE_RUNNERS}" --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic github-pat-secret \
    --namespace "${NAMESPACE_RUNNERS}" \
    --from-literal=github_token="${GITHUB_PAT}" \
    --dry-run=client -o yaml | kubectl apply -f -
echo ""

# Step 6: Install Runner Scale Set
echo -e "${GREEN}Step 6: Installing Runner Scale Set...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Determine storage class (local-path is used by k3s and local-path-provisioner)
STORAGE_CLASS="local-path"
if ! kubectl get storageclass "${STORAGE_CLASS}" &>/dev/null; then
    # Try to find any available storage class
    STORAGE_CLASS=$(kubectl get storageclass -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "local-path")
    echo -e "${YELLOW}Using storage class: ${STORAGE_CLASS}${NC}"
fi

helm install "${INSTALLATION_NAME}" \
    --namespace "${NAMESPACE_RUNNERS}" \
    --create-namespace \
    --set githubConfigUrl="${GITHUB_CONFIG_URL}" \
    --set githubConfigSecret.github_token="${GITHUB_PAT}" \
    --set containerMode.type="kubernetes" \
    --set containerMode.kubernetesModeWorkVolumeClaim.storageClassName="${STORAGE_CLASS}" \
    --set containerMode.kubernetesModeWorkVolumeClaim.accessModes[0]="ReadWriteOnce" \
    --set containerMode.kubernetesModeWorkVolumeClaim.resources.requests.storage="10Gi" \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
echo ""

# Step 7: Check GPU Resources and Apply Appropriate Kyverno Policy
echo -e "${GREEN}Step 7: Checking GPU resources...${NC}"
if kubectl get node "${NODE_NAME}" -o json 2>/dev/null | grep -qi "gpu\|amd\|rocm" || kubectl describe node "${NODE_NAME}" 2>/dev/null | grep -qi "gpu\|amd\|rocm"; then
    echo "GPU resources detected, applying full policy with resource requests..."
    kubectl apply -f "${SCRIPT_DIR}/amd-gpu-kyverno-policy.yaml"
else
    echo "No GPU resources detected in Kubernetes (no device plugin)."
    echo "Applying node-selector-only policy..."
    kubectl apply -f "${SCRIPT_DIR}/amd-gpu-kyverno-policy-no-device-plugin.yaml"
    echo -e "${YELLOW}Note: You'll need to configure ARC max runners to limit concurrent pods.${NC}"
fi
echo ""

# Step 8: Apply LimitRange
echo -e "${GREEN}Step 8: Applying GPU LimitRange...${NC}"
kubectl apply -f "${SCRIPT_DIR}/amd-gpu-limitrange.yaml"
echo ""

# Step 9: Wait for runners to be ready
echo -e "${GREEN}Step 9: Waiting for runner scale set to be ready...${NC}"
sleep 10
kubectl wait --for=condition=ready autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE_RUNNERS}" --timeout=300s || echo -e "${YELLOW}Timeout waiting for runner scale set (this may be normal)${NC}"
echo ""

# Summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Check runner scale set status:"
echo "   kubectl get autoscalingrunnersets -n ${NAMESPACE_RUNNERS}"
echo ""
echo "2. Get the runner label (update your workflow with this):"
echo "   kubectl get autoscalingrunnersets -n ${NAMESPACE_RUNNERS} -o jsonpath='{.items[0].status.runnerLabel}'"
echo ""
echo "3. Check runner pods:"
echo "   kubectl get pods -n ${NAMESPACE_RUNNERS}"
echo ""
echo "4. Test GPU allocation (optional):"
echo "   kubectl apply -f ${SCRIPT_DIR}/amd-gpu-test-pod.yaml"
echo "   kubectl describe pod -n ${NAMESPACE_RUNNERS} amd-gpu-test-pod"
echo ""
echo -e "${YELLOW}Note: The resource name 'amd.com/gpu' may need adjustment based on your device plugin.${NC}"
echo -e "${YELLOW}Check 'kubectl describe node ${NODE_NAME}' to see available GPU resources.${NC}"

