#!/bin/bash
# Quick GPU test script
# This creates a test pod to verify GPU access works without hangs

set -e

export KUBECONFIG=~/.kube/config

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Quick GPU Test ==="
echo ""
echo "This will create a test pod to verify GPU access..."
echo ""

# Apply test pod
echo "Creating test pod..."
kubectl apply -f "${SCRIPT_DIR}/quick-gpu-test.yaml"

echo ""
echo "Waiting for pod to start..."
sleep 5

# Wait for pod to be running
echo "Waiting for pod to be ready..."
kubectl wait --for=condition=Ready pod/quick-gpu-test -n arc-runners --timeout=60s || {
    echo "ERROR: Pod did not become ready"
    kubectl describe pod quick-gpu-test -n arc-runners
    kubectl delete pod quick-gpu-test -n arc-runners --ignore-not-found
    exit 1
}

echo ""
echo "Pod is running. Checking logs (with 60 second timeout)..."
echo ""

# Get logs with timeout (to detect hangs)
if timeout 60 kubectl logs -f quick-gpu-test -n arc-runners 2>&1; then
    echo ""
    echo "=== Test completed successfully ==="
    echo ""
    
    # Check pod status
    POD_STATUS=$(kubectl get pod quick-gpu-test -n arc-runners -o jsonpath='{.status.phase}')
    echo "Pod status: ${POD_STATUS}"
    
    if [ "$POD_STATUS" = "Succeeded" ]; then
        echo ""
        echo "✅ GPU test PASSED - No hangs detected"
        echo ""
        # Cleanup
        kubectl delete pod quick-gpu-test -n arc-runners
        exit 0
    else
        echo ""
        echo "⚠️  Pod status is ${POD_STATUS} (expected Succeeded)"
        exit 1
    fi
else
    TIMEOUT_EXIT=$?
    if [ $TIMEOUT_EXIT -eq 124 ]; then
        echo ""
        echo "❌ TEST FAILED: Timeout - GPU appears to be hanging"
        echo ""
        echo "Pod may be stuck. Checking status..."
        kubectl get pod quick-gpu-test -n arc-runners
        echo ""
        echo "You may need to manually delete the pod:"
        echo "  kubectl delete pod quick-gpu-test -n arc-runners"
        exit 1
    else
        echo ""
        echo "❌ Test failed with exit code: $TIMEOUT_EXIT"
        kubectl get pod quick-gpu-test -n arc-runners
        exit 1
    fi
fi

