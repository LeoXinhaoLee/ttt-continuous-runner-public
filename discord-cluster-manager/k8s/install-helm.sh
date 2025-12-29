#!/bin/bash
#
# Install Helm (doesn't require root if installing to user directory)

set -e

echo "Installing Helm..."

# Check if helm is already installed
if command -v helm &> /dev/null; then
    echo "Helm is already installed:"
    helm version
    exit 0
fi

# Option 1: Install to user directory (no root needed)
INSTALL_DIR="${HOME}/.local/bin"
mkdir -p "${INSTALL_DIR}"

# Download and install Helm
HELM_VERSION="v3.14.4"  # Latest stable version as of writing
ARCH="linux-amd64"

echo "Downloading Helm ${HELM_VERSION}..."
curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-${ARCH}.tar.gz" -o /tmp/helm.tar.gz

echo "Extracting..."
tar -xzf /tmp/helm.tar.gz -C /tmp

echo "Installing to ${INSTALL_DIR}..."
mv /tmp/${ARCH}/helm "${INSTALL_DIR}/helm"
rm -rf /tmp/${ARCH} /tmp/helm.tar.gz

# Add to PATH if not already there
if [[ ":$PATH:" != *":${INSTALL_DIR}:"* ]]; then
    echo ""
    echo "Adding ${INSTALL_DIR} to PATH..."
    echo "export PATH=\"${INSTALL_DIR}:\$PATH\"" >> ~/.bashrc
    export PATH="${INSTALL_DIR}:$PATH"
    echo "Run 'source ~/.bashrc' or restart your shell to use helm"
fi

echo ""
echo "Helm installed successfully to ${INSTALL_DIR}/helm"
echo ""
echo "Verify installation:"
"${INSTALL_DIR}/helm" version

echo ""
echo "If helm command is not found, run:"
echo "  export PATH=\"${INSTALL_DIR}:\$PATH\""
echo "Or restart your shell"




