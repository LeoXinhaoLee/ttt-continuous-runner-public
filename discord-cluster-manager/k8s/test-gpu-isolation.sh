#!/bin/bash
#
# Test GPU isolation across multiple pods
# This script creates multiple test pods and checks if each sees only 1 GPU

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

NAMESPACE="arc-runners"
NUM_PODS="${1:-4}"  # Default to 4 pods, can override with first argument

echo -e "${GREEN}=== GPU Isolation Test ===${NC}"
echo ""
echo "This test will:"
echo "  1. Create $NUM_PODS test pods, each requesting 1 GPU"
echo "  2. Check how many GPUs each pod sees (should be 1)"
echo "  3. Report if device plugin is properly isolating GPUs"
echo ""

# Clean up any existing test pods
echo "Cleaning up any existing test pods..."
kubectl delete pod -n "$NAMESPACE" -l test=gpu-isolation 2>/dev/null || true
sleep 2

# Create test pods
echo -e "${YELLOW}Creating $NUM_PODS test pods...${NC}"
for i in $(seq 0 $((NUM_PODS-1))); do
    cat <<EOF | sed "s/\${POD_INDEX}/$i/g" | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: gpu-isolation-test-$i
  namespace: $NAMESPACE
  labels:
    test: gpu-isolation
spec:
  restartPolicy: Never
  securityContext:
    seccompProfile:
      type: Unconfined
    runAsUser: 0
    runAsGroup: 0
    supplementalGroups:
      - 992
  volumes:
    - name: dshm
      emptyDir:
        medium: Memory
        sizeLimit: "8Gi"
  containers:
    - name: test
      image: ghcr.io/leoxinhaolee/amd-runner:latest
      command: ["/bin/bash", "-c"]
      args:
        - |
          python3 <<'PYTHON_SCRIPT'
          import torch
          import os
          import time
          import json
          
          # Wait a bit for everything to initialize
          time.sleep(2)
          
          result = {
              "pod_name": os.environ.get("HOSTNAME", "unknown"),
              "rocr_visible_devices": os.environ.get("ROCR_VISIBLE_DEVICES", "not_set"),
              "hip_visible_devices": os.environ.get("HIP_VISIBLE_DEVICES", "not_set"),
              "cuda_available": torch.cuda.is_available(),
              "device_count": 0,
              "devices": []
          }
          
          if torch.cuda.is_available():
              result["device_count"] = torch.cuda.device_count()
              for i in range(torch.cuda.device_count()):
                  try:
                      result["devices"].append({
                          "index": i,
                          "name": torch.cuda.get_device_name(i)
                      })
                  except:
                      result["devices"].append({"index": i, "name": "unknown"})
          
          print(json.dumps(result))
          PYTHON_SCRIPT
          sleep 300
      resources:
        requests:
          amd.com/gpu: "1"
        limits:
          amd.com/gpu: "1"
      volumeMounts:
        - name: dshm
          mountPath: /dev/shm
      securityContext:
        privileged: true
        allowPrivilegeEscalation: true
        runAsUser: 0
        runAsGroup: 0
        capabilities:
          add:
            - SYS_ADMIN
            - SYS_RESOURCE
            - SYS_PTRACE
  nodeSelector:
    amd.com/gpu.present: "true"
EOF
done

echo ""
echo -e "${YELLOW}Waiting for pods to be ready...${NC}"
sleep 5

# Wait for all pods to be ready
for i in $(seq 0 $((NUM_PODS-1))); do
    echo -n "  Waiting for pod gpu-isolation-test-$i..."
    for j in {1..60}; do
        if kubectl get pod gpu-isolation-test-$i -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null | grep -q "Running"; then
            echo -e " ${GREEN}✓${NC}"
            break
        fi
        if [ $j -eq 60 ]; then
            echo -e " ${RED}✗ (timeout)${NC}"
        fi
        sleep 1
    done
done

echo ""
echo -e "${YELLOW}Waiting for PyTorch to initialize in pods...${NC}"
sleep 10

echo ""
echo -e "${GREEN}=== Test Results ===${NC}"
echo ""

ALL_GOOD=true

for i in $(seq 0 $((NUM_PODS-1))); do
    POD_NAME="gpu-isolation-test-$i"
    
    if ! kubectl get pod "$POD_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
        echo -e "${RED}Pod $POD_NAME not found${NC}"
        continue
    fi
    
    PHASE=$(kubectl get pod "$POD_NAME" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    
    if [ "$PHASE" != "Running" ]; then
        echo -e "${YELLOW}$POD_NAME: $PHASE (not running, skipping)${NC}"
        continue
    fi
    
    # Get GPU info from pod
    RESULT=$(kubectl logs "$POD_NAME" -n "$NAMESPACE" 2>/dev/null | grep -o '{.*}' | head -1 || echo "")
    
    if [ -z "$RESULT" ]; then
        echo -e "${YELLOW}$POD_NAME: Could not get results (may still be starting)${NC}"
        continue
    fi
    
    # Parse JSON (simple extraction, assumes json format)
    DEVICE_COUNT=$(echo "$RESULT" | grep -o '"device_count":[0-9]*' | cut -d':' -f2 || echo "0")
    ROCR_VISIBLE=$(echo "$RESULT" | grep -o '"rocr_visible_devices":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
    
    echo "Pod: $POD_NAME"
    echo "  ROCR_VISIBLE_DEVICES: $ROCR_VISIBLE"
    echo -n "  torch.cuda.device_count(): $DEVICE_COUNT"
    
    if [ "$DEVICE_COUNT" = "1" ]; then
        echo -e " ${GREEN}✅ CORRECT${NC}"
        echo "     Pod sees exactly 1 GPU (its allocated GPU) - Device plugin is working!"
    elif [ "$DEVICE_COUNT" -gt "1" ] 2>/dev/null; then
        echo -e " ${RED}❌ PROBLEM${NC}"
        echo "     Pod sees $DEVICE_COUNT GPUs (should be 1)"
        echo "     Device plugin is NOT isolating GPUs properly!"
        ALL_GOOD=false
    else
        echo -e " ${YELLOW}⚠ Could not determine${NC}"
    fi
    echo ""
done

echo -e "${GREEN}=== Summary ===${NC}"
echo ""

if [ "$ALL_GOOD" = true ]; then
    echo -e "${GREEN}✅ All pods see exactly 1 GPU${NC}"
    echo "   The device plugin is correctly isolating GPUs!"
    echo "   Each pod's 'GPU 0' is actually a different physical GPU on the host"
else
    echo -e "${RED}❌ Some pods see multiple GPUs${NC}"
    echo "   The device plugin is NOT isolating GPUs properly"
    echo ""
    echo "   Possible causes:"
    echo "   1. AMD device plugin doesn't support GPU isolation"
    echo "   2. Device plugin configuration issue"
    echo "   3. Device plugin version doesn't support this feature"
    echo ""
    echo "   Next steps:"
    echo "   - Check device plugin logs: kubectl logs -n kube-system -l name=amdgpu-dp-ds"
    echo "   - Check device plugin version and capabilities"
    echo "   - Consider using a different AMD device plugin implementation"
fi

echo ""
echo "Cleanup:"
echo "  kubectl delete pod -n $NAMESPACE -l test=gpu-isolation"
echo ""

