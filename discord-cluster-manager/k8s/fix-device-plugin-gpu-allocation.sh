#!/bin/bash
#
# Fix AMD GPU device plugin when it shows 0 available GPUs
# This restarts the device plugin pod to reset its allocation state
#
# Usage: ./fix-device-plugin-gpu-allocation.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

NAMESPACE="kube-system"

echo -e "${GREEN}=== Fixing AMD GPU Device Plugin Allocation ===${NC}"
echo ""

# Check if device plugin pod exists
DEVICE_PLUGIN_POD=$(kubectl get pods -n "${NAMESPACE}" -o name | grep amdgpu-device-plugin | head -1)

if [ -z "$DEVICE_PLUGIN_POD" ]; then
    echo -e "${RED}Error: AMD GPU device plugin pod not found${NC}"
    exit 1
fi

echo "Found device plugin pod: ${DEVICE_PLUGIN_POD}"
echo ""

# Check current GPU allocation
echo -e "${YELLOW}Current GPU allocation status:${NC}"
NODE_NAME=$(kubectl get nodes -o name | head -1 | cut -d/ -f2)
kubectl describe node "${NODE_NAME}" | grep -A 5 "amd.com/gpu" | head -10
echo ""

# Check for stuck pods requesting GPU
echo -e "${YELLOW}Checking for pods requesting GPU:${NC}"
STUCK_PODS=$(kubectl get pods -A -o json 2>/dev/null | jq -r '[.items[] | select(.spec.containers[0].resources.requests."amd.com/gpu" and .status.phase != "Running" and .status.phase != "Succeeded")] | length' 2>/dev/null || echo "0")
echo "Found ${STUCK_PODS} non-running pods with GPU requests"
echo ""

if [ "$STUCK_PODS" != "0" ]; then
    echo -e "${YELLOW}Warning: There are ${STUCK_PODS} pods in non-running state with GPU requests${NC}"
    echo "These might be holding GPU allocations. Consider cleaning them up:"
    echo "  kubectl get pods -A -o json | jq -r '.items[] | select(.spec.containers[0].resources.requests.\"amd.com/gpu\" and .status.phase != \"Running\" and .status.phase != \"Succeeded\") | \"kubectl delete pod -n \(.metadata.namespace) \(.metadata.name)\"'"
    echo ""
fi

# Restart device plugin pod
echo -e "${YELLOW}Restarting device plugin pod...${NC}"
kubectl delete "${DEVICE_PLUGIN_POD}" -n "${NAMESPACE}"
echo ""

# Wait for pod to restart
echo "Waiting for device plugin pod to restart..."
sleep 5

# Check if pod is running
MAX_WAIT=30
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if kubectl get pods -n "${NAMESPACE}" | grep amdgpu-device-plugin | grep -q Running; then
        echo -e "${GREEN}✓ Device plugin pod is running${NC}"
        break
    fi
    echo "Waiting... (${WAITED}s/${MAX_WAIT}s)"
    sleep 2
    WAITED=$((WAITED + 2))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo -e "${RED}Error: Device plugin pod did not start within ${MAX_WAIT} seconds${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}Updated GPU allocation status:${NC}"
kubectl describe node "${NODE_NAME}" | grep -A 5 "amd.com/gpu" | head -10
echo ""

echo -e "${GREEN}=== Fix Complete ===${NC}"
echo ""
echo "If you still see 'Available: 0' errors, check:"
echo "  1. All 8 GPUs are detected: kubectl describe node | grep 'amd.com/gpu'"
echo "  2. No stuck pods holding GPU allocations"
echo "  3. Device plugin logs: kubectl logs -n ${NAMESPACE} -l app=amdgpu-device-plugin --tail=50"

