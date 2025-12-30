#!/bin/bash
#
# Restart k3s service to fix kubelet/device-plugin allocation state issues
# Use this if you still get UnexpectedAdmissionError after implementing
# concurrency limits and maxRunners
#
# Usage: ./restart-k3s.sh
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Restarting k3s Service ===${NC}"
echo ""
echo -e "${YELLOW}Warning: This will restart k3s/kubelet on this node.${NC}"
echo "This will temporarily disrupt all Kubernetes workloads."
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}Note: This script requires root privileges.${NC}"
    echo "Attempting with sudo..."
    SUDO_CMD="sudo"
else
    SUDO_CMD=""
fi

echo "Stopping k3s service..."
$SUDO_CMD systemctl stop k3s 2>/dev/null || $SUDO_CMD systemctl stop k3s-agent 2>/dev/null || {
    echo -e "${YELLOW}Could not stop via systemctl, trying direct kill...${NC}"
    $SUDO_CMD pkill -9 k3s || true
}

echo "Waiting 3 seconds..."
sleep 3

echo "Starting k3s service..."
$SUDO_CMD systemctl start k3s 2>/dev/null || $SUDO_CMD systemctl start k3s-agent 2>/dev/null || {
    echo -e "${RED}Error: Could not start k3s service${NC}"
    echo "You may need to start it manually:"
    echo "  sudo systemctl start k3s"
    exit 1
}

echo ""
echo "Waiting for k3s to be ready..."
sleep 10

# Wait for API server to be ready
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if kubectl get nodes &>/dev/null; then
        echo -e "${GREEN}✓ k3s is ready${NC}"
        break
    fi
    echo "Waiting for k3s API server... (${WAITED}s/${MAX_WAIT}s)"
    sleep 2
    WAITED=$((WAITED + 2))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo -e "${RED}Warning: k3s did not become ready within ${MAX_WAIT} seconds${NC}"
    echo "Check status manually: sudo systemctl status k3s"
    exit 1
fi

echo ""
echo -e "${GREEN}=== k3s Restart Complete ===${NC}"
echo ""
echo "k3s/kubelet has been restarted. This should reset any stuck device allocation state."
echo ""
echo "Verify everything is working:"
echo "  kubectl get nodes"
echo "  kubectl get pods -n arc-runners"
echo "  kubectl describe node | grep amd.com/gpu"

