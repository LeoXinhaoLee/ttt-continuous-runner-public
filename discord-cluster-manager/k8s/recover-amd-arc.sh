#!/bin/bash
# Quick recovery script for AMD ARC setup after server restart
# Usage: ./recover-amd-arc.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

export KUBECONFIG=~/.kube/config

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${GREEN}=== AMD ARC Recovery Script ===${NC}"
echo ""

# Step 1: Check k3s
echo -e "${GREEN}Step 1: Checking k3s service...${NC}"
if ! systemctl is-active --quiet k3s; then
    echo -e "${YELLOW}k3s is not running. Starting...${NC}"
    sudo systemctl start k3s
    sleep 5
    if systemctl is-active --quiet k3s; then
        echo -e "${GREEN}✓ k3s started successfully${NC}"
    else
        echo -e "${RED}✗ Failed to start k3s${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ k3s is running${NC}"
fi
echo ""

# Step 2: Verify kubectl access
echo -e "${GREEN}Step 2: Verifying Kubernetes access...${NC}"
if ! kubectl get nodes > /dev/null 2>&1; then
    echo -e "${RED}✗ Cannot access Kubernetes cluster${NC}"
    echo "Please check your KUBECONFIG: $KUBECONFIG"
    exit 1
fi
NODE_COUNT=$(kubectl get nodes --no-headers | wc -l)
echo -e "${GREEN}✓ Kubernetes accessible (${NODE_COUNT} node(s))${NC}"
echo ""

# Step 3: Check components
echo -e "${GREEN}Step 3: Checking component status...${NC}"

# ARC system
ARC_PODS=$(kubectl get pods -n arc-systems --no-headers 2>/dev/null | wc -l || echo "0")
if [ "$ARC_PODS" -gt "0" ]; then
    ARC_RUNNING=$(kubectl get pods -n arc-systems --no-headers 2>/dev/null | grep Running | wc -l || echo "0")
    echo "  ARC system: ${ARC_RUNNING}/${ARC_PODS} pods running"
else
    echo -e "  ${YELLOW}ARC system: No pods found (may need reinstall)${NC}"
fi

# Kyverno
KYVERNO_PODS=$(kubectl get pods -n kyverno --no-headers 2>/dev/null | grep -v Completed | wc -l || echo "0")
if [ "$KYVERNO_PODS" -gt "0" ]; then
    KYVERNO_RUNNING=$(kubectl get pods -n kyverno --no-headers 2>/dev/null | grep Running | wc -l || echo "0")
    echo "  Kyverno: ${KYVERNO_RUNNING}/${KYVERNO_PODS} pods running"
else
    echo -e "  ${YELLOW}Kyverno: Not installed${NC}"
fi

# AMD GPU device plugin
AMD_PODS=$(kubectl get pods -n kube-system --no-headers 2>/dev/null | grep amdgpu | wc -l || echo "0")
if [ "$AMD_PODS" -gt "0" ]; then
    AMD_RUNNING=$(kubectl get pods -n kube-system --no-headers 2>/dev/null | grep amdgpu | grep Running | wc -l || echo "0")
    echo "  AMD GPU device plugin: ${AMD_RUNNING}/${AMD_PODS} pods running"
else
    echo -e "  ${YELLOW}AMD GPU device plugin: Not installed (may need installation)${NC}"
fi

# ARC runner set
ARC_RUNNER_SET=$(kubectl get autoscalingrunnersets -n arc-runners --no-headers 2>/dev/null | wc -l || echo "0")
if [ "$ARC_RUNNER_SET" -gt "0" ]; then
    echo "  ARC runner scale set: Found"
else
    echo -e "  ${YELLOW}ARC runner scale set: Not found${NC}"
fi
echo ""

# Step 4: Reapply Kyverno policy
echo -e "${GREEN}Step 4: Reapplying Kyverno GPU policy...${NC}"
POLICY_FILE="${SCRIPT_DIR}/amd-gpu-kyverno-policy.yaml"
if [ -f "$POLICY_FILE" ]; then
    if kubectl apply -f "$POLICY_FILE" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Kyverno policy applied${NC}"
    else
        echo -e "${RED}✗ Failed to apply Kyverno policy${NC}"
        exit 1
    fi
else
    echo -e "${RED}✗ Policy file not found: ${POLICY_FILE}${NC}"
    exit 1
fi
echo ""

# Step 5: Verify Kyverno policy
echo -e "${GREEN}Step 5: Verifying Kyverno policy...${NC}"
if kubectl get clusterpolicy inject-amd-gpu-resources > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Kyverno policy exists${NC}"
else
    echo -e "${RED}✗ Kyverno policy not found${NC}"
fi

# Step 6: Verify GPU resources
echo -e "${GREEN}Step 6: Verifying GPU resources...${NC}"
GPU_COUNT=$(kubectl get nodes -o jsonpath='{.items[0].status.capacity.amd\.com/gpu}' 2>/dev/null || echo "0")
if [ "$GPU_COUNT" != "0" ] && [ -n "$GPU_COUNT" ]; then
    echo -e "${GREEN}✓ GPU resources available: ${GPU_COUNT} GPU(s)${NC}"
else
    echo -e "${YELLOW}⚠ GPU resources not detected (check device plugin)${NC}"
fi
echo ""

# Summary
echo -e "${GREEN}=== Recovery Summary ===${NC}"
echo "k3s: $(systemctl is-active k3s || echo 'not running')"
echo "Kubernetes nodes: ${NODE_COUNT}"
echo "ARC runner sets: ${ARC_RUNNER_SET}"
echo "Setup: Device plugin (AMD k8s-device-plugin)"
echo ""
echo -e "${GREEN}Recovery complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Verify components: kubectl get pods --all-namespaces"
echo "  2. Test GPU access: See RECOVERY-AFTER-RESTART.md for test commands"
echo "  3. Check ARC status: kubectl get autoscalingrunnersets -n arc-runners"

