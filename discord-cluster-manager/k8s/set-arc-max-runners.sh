#!/bin/bash
#
# Set ARC maxRunners to prevent over-provisioning beyond GPU capacity
#
# Usage: ./set-arc-max-runners.sh [max_runners]
#   max_runners: Maximum number of concurrent runners (default: 8, matching GPU count)
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

NAMESPACE_RUNNERS="arc-runners"
INSTALLATION_NAME="amd-arc-runner"

# Default to 8 runners (matching 8 GPUs)
MAX_RUNNERS="${1:-8}"

echo -e "${GREEN}=== Setting ARC maxRunners ===${NC}"
echo ""

# Check if AutoscalingRunnerSet exists
if ! kubectl get autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE_RUNNERS}" &>/dev/null; then
    echo -e "${RED}Error: AutoscalingRunnerSet '${INSTALLATION_NAME}' not found in namespace '${NAMESPACE_RUNNERS}'${NC}"
    exit 1
fi

# Check if Helm release exists
if helm list -n "${NAMESPACE_RUNNERS}" | grep -q "${INSTALLATION_NAME}"; then
    echo "Updating ARC via Helm..."
    helm upgrade "${INSTALLATION_NAME}" \
        --namespace "${NAMESPACE_RUNNERS}" \
        --reuse-values \
        --set maxRunners="${MAX_RUNNERS}" \
        oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
    
    echo -e "${GREEN}✓ Updated ARC maxRunners to ${MAX_RUNNERS} via Helm${NC}"
else
    echo -e "${YELLOW}Helm release not found. Attempting direct patch...${NC}"
    # Try to patch the AutoscalingRunnerSet directly
    kubectl patch autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE_RUNNERS}" \
        --type='json' -p="[{\"op\": 'add', 'path': '/spec/maxRunners', 'value': ${MAX_RUNNERS}}]" 2>/dev/null || \
    kubectl patch autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE_RUNNERS}" \
        --type='json' -p="[{\"op\": 'replace', 'path': '/spec/maxRunners', 'value': ${MAX_RUNNERS}}]"
    
    echo -e "${GREEN}✓ Updated ARC maxRunners to ${MAX_RUNNERS} via kubectl patch${NC}"
fi

echo ""
echo "Waiting 5 seconds for ARC to reconcile..."
sleep 5

echo ""
echo -e "${GREEN}Current ARC status:${NC}"
kubectl get autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE_RUNNERS}" -o wide

echo ""
echo -e "${GREEN}=== Configuration Complete ===${NC}"
echo ""
echo "ARC is now configured to create a maximum of ${MAX_RUNNERS} concurrent runners."
echo "This prevents over-provisioning beyond your GPU capacity (8 GPUs)."
echo ""
echo "Note: This doesn't queue pods inside Kubernetes, but prevents ARC from"
echo "spinning up more runners than your GPUs can serve."

