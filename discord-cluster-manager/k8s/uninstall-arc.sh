#!/bin/bash
#
# Uninstall ARC Runner Scale Set
# Usage: ./uninstall-arc.sh [INSTALLATION_NAME]

set -e

INSTALLATION_NAME="${1:-amd-arc-runner}"
NAMESPACE="arc-runners"

echo "Uninstalling ARC Runner Scale Set: ${INSTALLATION_NAME}"
echo ""

# Set kubeconfig if needed
if [ -f ~/.kube/config ] && [ -z "$KUBECONFIG" ]; then
    export KUBECONFIG=~/.kube/config
fi

# Uninstall Helm release
if helm list -n "${NAMESPACE}" 2>/dev/null | grep -q "${INSTALLATION_NAME}"; then
    echo "Uninstalling Helm release: ${INSTALLATION_NAME}"
    helm uninstall "${INSTALLATION_NAME}" --namespace "${NAMESPACE}" 2>/dev/null || true
    echo "Helm release uninstalled"
else
    echo "No Helm release found with name: ${INSTALLATION_NAME}"
fi

# Delete AutoscalingRunnerSet if exists
if kubectl get autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE}" &>/dev/null; then
    echo "Deleting AutoscalingRunnerSet: ${INSTALLATION_NAME}"
    kubectl delete autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE}" || true
    echo "AutoscalingRunnerSet deleted"
fi

echo ""
echo "Uninstallation complete!"
echo ""
echo "To completely remove ARC, you may also want to:"
echo "  - Delete namespace: kubectl delete namespace ${NAMESPACE}"
echo "  - Uninstall ARC controller: helm uninstall arc -n arc-systems"
echo "  - Uninstall Kyverno: helm uninstall kyverno -n kyverno"

