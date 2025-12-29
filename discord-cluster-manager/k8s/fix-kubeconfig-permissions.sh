#!/bin/bash
#
# Fix k3s kubeconfig permissions for non-root users
# This copies the kubeconfig to your home directory and sets proper permissions

set -e

USER_HOME="${HOME}"
KUBECONFIG_DIR="${USER_HOME}/.kube"
KUBECONFIG_FILE="${KUBECONFIG_DIR}/config"

echo "Fixing k3s kubeconfig permissions..."

# Create .kube directory if it doesn't exist
mkdir -p "${KUBECONFIG_DIR}"

# Copy kubeconfig from system location to user directory
echo "Copying kubeconfig to ${KUBECONFIG_FILE}..."
sudo cp /etc/rancher/k3s/k3s.yaml "${KUBECONFIG_FILE}"

# Change ownership to current user
echo "Setting ownership to ${USER}..."
sudo chown "${USER}:${USER}" "${KUBECONFIG_FILE}"

# Set proper permissions (read/write for owner only)
chmod 600 "${KUBECONFIG_FILE}"

# Set KUBECONFIG environment variable
echo ""
echo "Kubeconfig has been set up at: ${KUBECONFIG_FILE}"
echo ""
echo "To use kubectl, either:"
echo "  1. Add to your shell profile (recommended):"
echo "     echo 'export KUBECONFIG=${KUBECONFIG_FILE}' >> ~/.bashrc"
echo "     source ~/.bashrc"
echo ""
echo "  2. Or export it in your current shell:"
echo "     export KUBECONFIG=${KUBECONFIG_FILE}"
echo ""

# Try to add to bashrc if it exists and KUBECONFIG is not already set
if [ -f "${USER_HOME}/.bashrc" ] && ! grep -q "export KUBECONFIG=" "${USER_HOME}/.bashrc"; then
    read -p "Add KUBECONFIG to ~/.bashrc? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "export KUBECONFIG=${KUBECONFIG_FILE}" >> "${USER_HOME}/.bashrc"
        echo "Added to ~/.bashrc. Run 'source ~/.bashrc' or restart your shell."
    fi
fi

# Export for current shell
export KUBECONFIG="${KUBECONFIG_FILE}"

echo "Testing kubectl..."
kubectl get nodes

echo ""
echo "✅ Success! kubectl is now configured for user ${USER}"




