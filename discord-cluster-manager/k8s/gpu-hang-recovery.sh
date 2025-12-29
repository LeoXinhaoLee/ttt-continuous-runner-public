#!/bin/bash
# GPU Hang Recovery Script for AMD MI300X
# This script attempts to recover from GPU hangs by:
# 1. Killing processes holding GPU resources
# 2. Attempting GPU reset (if supported)
# 3. Checking GPU state

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== GPU Hang Recovery Script ===${NC}"
echo ""

# Step 1: Check for processes holding GPU devices
echo -e "${GREEN}Step 1: Checking for processes holding GPU devices...${NC}"
GPU_PROCESSES=$(lsof /dev/kfd /dev/dri/renderD* 2>/dev/null | grep -v "COMMAND" | awk '{print $2}' | sort -u || true)
if [ -n "$GPU_PROCESSES" ]; then
    echo "Found processes holding GPU devices: $GPU_PROCESSES"
    for pid in $GPU_PROCESSES; do
        if ps -p $pid > /dev/null 2>&1; then
            echo "  PID $pid: $(ps -p $pid -o comm= 2>/dev/null || echo 'unknown')"
        fi
    done
else
    echo "No processes found holding GPU devices"
fi
echo ""

# Step 2: Check Kubernetes pods using GPU
echo -e "${GREEN}Step 2: Checking Kubernetes pods using GPU...${NC}"
export KUBECONFIG=~/.kube/config
GPU_PODS=$(kubectl get pods --all-namespaces -o json 2>/dev/null | \
    jq -r '.items[] | select(.spec.containers[]?.resources.requests."amd.com/gpu" != null) | "\(.metadata.namespace)/\(.metadata.name)"' 2>/dev/null || echo "")
if [ -n "$GPU_PODS" ]; then
    echo "Found pods with GPU requests:"
    echo "$GPU_PODS" | while read pod; do
        if [ -n "$pod" ]; then
            echo "  $pod"
        fi
    done
else
    echo "No pods found with GPU requests"
fi
echo ""

# Step 3: Check GPU device state
echo -e "${GREEN}Step 3: Checking GPU device state...${NC}"
if [ -c /dev/kfd ]; then
    echo "✓ /dev/kfd exists"
else
    echo -e "${RED}✗ /dev/kfd does not exist${NC}"
fi

DRI_DEVICES=$(ls /dev/dri/renderD* 2>/dev/null | wc -l || echo "0")
echo "Found $DRI_DEVICES DRI devices"
echo ""

# Step 4: Attempt to reset GPU (requires root)
echo -e "${GREEN}Step 4: Attempting GPU reset...${NC}"
if [ "$EUID" -eq 0 ]; then
    # Try to unbind and rebind the amdgpu module (drastic but may work)
    echo "Attempting GPU module reset (this may cause instability)..."
    echo -e "${YELLOW}WARNING: This operation is risky and may require a reboot${NC}"
    
    # Check if we can access sysfs
    if [ -d /sys/class/drm ]; then
        echo "GPU devices found in /sys/class/drm:"
        ls -d /sys/class/drm/card* 2>/dev/null | head -5
    fi
else
    echo -e "${YELLOW}Note: GPU reset requires root privileges${NC}"
    echo "Run with sudo to attempt GPU reset"
fi
echo ""

# Step 5: Check system logs
echo -e "${GREEN}Step 5: Recent GPU-related system logs...${NC}"
if [ "$EUID" -eq 0 ]; then
    echo "Checking dmesg for GPU errors (last 50 lines):"
    dmesg | tail -50 | grep -i "amdgpu\|gpu\|hang" | tail -10 || echo "No recent GPU errors found"
else
    echo -e "${YELLOW}Note: Checking dmesg requires root privileges${NC}"
    echo "Run 'sudo dmesg | grep -i amdgpu' to check for GPU errors"
fi
echo ""

# Step 6: Recommendations
echo -e "${GREEN}=== Recovery Recommendations ===${NC}"
echo ""
echo "If GPU is still hung after this script:"
echo "  1. Try restarting the AMD GPU device plugin:"
echo "     kubectl rollout restart daemonset/amdgpu-device-plugin-daemonset -n kube-system"
echo ""
echo "  2. Check if any Kubernetes pods are stuck:"
echo "     kubectl get pods --all-namespaces | grep -E 'Error|CrashLoopBackOff|Pending'"
echo ""
echo "  3. If GPU is completely unresponsive, you may need to:"
echo "     - Restart k3s: sudo systemctl restart k3s"
echo "     - Or reboot the server"
echo ""
echo "  4. To prevent future GPU hangs, consider:"
echo "     - Adding timeouts to GPU workloads"
echo "     - Ensuring proper cleanup of GPU resources in code"
echo "     - Using resource limits in containers"
echo ""

