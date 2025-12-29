#!/bin/bash
#
# Quick script to check GPU isolation in currently running workflow pods

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

NAMESPACE="arc-runners"

echo -e "${GREEN}=== Checking GPU Isolation in Running Workflow Pods ===${NC}"
echo ""

PODS=$(kubectl get pods -n "$NAMESPACE" --field-selector=status.phase=Running -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)

if [ -z "$PODS" ]; then
    echo "No running pods found in namespace $NAMESPACE"
    exit 0
fi

ALL_GOOD=true

for POD in $PODS; do
    echo "=== $POD ==="
    
    # Check environment variables
    ROCR_VISIBLE=$(kubectl exec -n "$NAMESPACE" "$POD" -- sh -c 'echo ${ROCR_VISIBLE_DEVICES:-not_set}' 2>/dev/null || echo "error")
    HIP_VISIBLE=$(kubectl exec -n "$NAMESPACE" "$POD" -- sh -c 'echo ${HIP_VISIBLE_DEVICES:-not_set}' 2>/dev/null || echo "error")
    
    echo "  ROCR_VISIBLE_DEVICES: $ROCR_VISIBLE"
    echo "  HIP_VISIBLE_DEVICES: $HIP_VISIBLE"
    
    # Check device count
    DEVICE_COUNT=$(kubectl exec -n "$NAMESPACE" "$POD" -- python3 -c "import torch; print(torch.cuda.device_count() if torch.cuda.is_available() else 0)" 2>/dev/null || echo "error")
    
    echo -n "  torch.cuda.device_count(): $DEVICE_COUNT"
    
    if [ "$DEVICE_COUNT" = "1" ]; then
        echo -e " ${GREEN}✅ CORRECT${NC}"
        echo "     Pod sees exactly 1 GPU (its allocated GPU)"
    elif [ "$DEVICE_COUNT" != "error" ] && [ -n "$DEVICE_COUNT" ] && [ "$DEVICE_COUNT" -gt "1" ] 2>/dev/null; then
        echo -e " ${RED}❌ PROBLEM${NC}"
        echo "     Pod sees $DEVICE_COUNT GPUs (should be 1)"
        echo "     Device plugin is NOT isolating GPUs!"
        ALL_GOOD=false
    elif [ "$DEVICE_COUNT" = "error" ]; then
        echo -e " ${YELLOW}⚠ Could not check (pod may still be starting)${NC}"
    else
        echo -e " ${YELLOW}⚠ Unexpected value${NC}"
    fi
    
    echo ""
done

echo -e "${GREEN}=== Summary ===${NC}"
if [ "$ALL_GOOD" = true ]; then
    echo -e "${GREEN}✅ All pods see exactly 1 GPU${NC}"
    echo "   Device plugin is correctly isolating GPUs!"
else
    echo -e "${RED}❌ Some pods see multiple GPUs${NC}"
    echo "   Device plugin is NOT isolating GPUs properly"
fi
echo ""

