#!/bin/bash
# Quick diagnostic script for ARC status

echo "=== ARC Controller Status ==="
kubectl get pods -n arc-systems
echo ""

echo "=== Runner Scale Set Status ==="
kubectl get autoscalingrunnersets -n arc-runners
echo ""

echo "=== Runner Label (use this in workflows) ==="
RUNNER_LABEL=$(kubectl get autoscalingrunnersets -n arc-runners -o jsonpath='{.items[0].status.runnerLabel}' 2>/dev/null)
if [ -n "$RUNNER_LABEL" ]; then
    echo "Runner label: $RUNNER_LABEL"
    echo "Use this in your workflow: runs-on: $RUNNER_LABEL"
else
    echo "ERROR: Runner label not found. Scale set may not be ready."
fi
echo ""

echo "=== Runner Pods ==="
kubectl get pods -n arc-runners
echo ""

echo "=== ARC Controller Logs (last 20 lines) ==="
kubectl logs -n arc-systems -l app.kubernetes.io/name=gha-runner-scale-set-controller --tail=20 2>/dev/null || echo "No controller logs found"
echo ""

echo "=== Scale Set Events ==="
kubectl get events -n arc-runners --sort-by='.lastTimestamp' | tail -10
