#!/bin/bash
#
# Check ARC configuration and diagnose queueing issues
#
# Usage: ./update-arc-max-runners.sh
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

NAMESPACE_RUNNERS="arc-runners"
INSTALLATION_NAME="amd-arc-runner"

echo -e "${GREEN}=== ARC Configuration and Diagnostics ===${NC}"
echo ""

# Check if AutoscalingRunnerSet exists
if ! kubectl get autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE_RUNNERS}" &>/dev/null; then
    echo -e "${RED}Error: AutoscalingRunnerSet '${INSTALLATION_NAME}' not found in namespace '${NAMESPACE_RUNNERS}'${NC}"
    exit 1
fi

echo -e "${YELLOW}1. ARC Status:${NC}"
kubectl get autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE_RUNNERS}" -o wide
echo ""

echo -e "${YELLOW}2. Current Runner Count:${NC}"
kubectl get autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE_RUNNERS}" -o jsonpath='Status - Current: {.status.currentRunners}, Running: {.status.runningEphemeralRunners}, Pending: {.status.pendingEphemeralRunners}' && echo ""
echo ""

echo -e "${YELLOW}3. Available GPU Resources:${NC}"
kubectl get nodes -o json | jq -r '.items[] | "\(.metadata.name): \(.status.capacity."amd.com/gpu" // "N/A") GPUs available"' 2>/dev/null || kubectl describe nodes | grep -E "Name:|amd.com/gpu" | head -10
echo ""

echo -e "${YELLOW}4. Running Pods:${NC}"
kubectl get pods -n "${NAMESPACE_RUNNERS}" -o wide
echo ""

echo -e "${YELLOW}5. ARC Controller Logs (last 20 lines, checking for errors):${NC}"
kubectl logs -n arc-systems -l app.kubernetes.io/name=gha-runner-scale-set-controller --tail=20 2>/dev/null | grep -i "error\|fail\|queue" || echo "No obvious errors in recent logs"
echo ""

echo -e "${GREEN}=== Understanding ARC Scaling ===${NC}"
echo ""
echo "ARC automatically scales based on:"
echo "  1. Available GPU resources (amd.com/gpu capacity)"
echo "  2. Job requests from GitHub Actions"
echo ""
echo "If you have 8 GPUs, ARC should create up to 8 concurrent runners."
echo ""
echo -e "${YELLOW}If jobs are failing when sending >8 requests:${NC}"
echo "  1. Check GitHub Actions queue timeout (jobs in 'queued' status can timeout)"
echo "  2. Verify all 8 GPUs are available: kubectl describe nodes | grep amd.com/gpu"
echo "  3. Check for resource constraints: kubectl describe pods -n ${NAMESPACE_RUNNERS}"
echo "  4. Review ARC controller logs for scaling issues"
echo ""
echo -e "${YELLOW}Note:${NC} ARC doesn't have a configurable maxRunners field."
echo "It scales automatically based on available resources (GPUs)."
echo "Jobs beyond available capacity will queue in GitHub Actions."
echo ""

