#!/bin/bash
#
# Complete deployment script for AMD GPU + ARC on k3s
# Usage: ./deploy-from-scratch.sh --github-url <URL> --github-pat <PAT> [--skip-tests]
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
GITHUB_URL=""
GITHUB_PAT=""
SKIP_TESTS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --github-url)
            GITHUB_URL="$2"
            shift 2
            ;;
        --github-pat)
            GITHUB_PAT="$2"
            shift 2
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 --github-url <URL> --github-pat <PAT> [--skip-tests]"
            exit 1
            ;;
    esac
done

# Validate required arguments
if [ -z "$GITHUB_URL" ] || [ -z "$GITHUB_PAT" ]; then
    echo -e "${RED}Error: --github-url and --github-pat are required${NC}"
    echo "Usage: $0 --github-url <URL> --github-pat <PAT> [--skip-tests]"
    exit 1
fi

# Set up kubeconfig
if [ ! -f ~/.kube/config ]; then
    if [ -f /etc/rancher/k3s/k3s.yaml ]; then
        echo -e "${YELLOW}Kubeconfig not found. Attempting to copy from /etc/rancher/k3s/k3s.yaml...${NC}"
        mkdir -p ~/.kube
        # Try with sudo if available, otherwise give instructions
        if command -v sudo &> /dev/null; then
            if sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config 2>/dev/null && sudo chown $USER:$USER ~/.kube/config 2>/dev/null; then
                echo -e "${GREEN}✓ Kubeconfig set up${NC}"
            else
                echo -e "${RED}✗ Failed to copy kubeconfig (sudo may require password). Please have root user run:${NC}"
                echo "  mkdir -p ~/.kube"
                echo "  cp /etc/rancher/k3s/k3s.yaml ~/.kube/config"
                echo "  chown $USER:$USER ~/.kube/config"
                exit 1
            fi
        else
            echo -e "${RED}✗ Sudo not available. Please have root user run:${NC}"
            echo "  mkdir -p ~/.kube"
            echo "  cp /etc/rancher/k3s/k3s.yaml ~/.kube/config"
            echo "  chown $USER:$USER ~/.kube/config"
            exit 1
        fi
    else
        echo -e "${RED}✗ Kubeconfig not found and k3s config not available${NC}"
        exit 1
    fi
fi

export KUBECONFIG=~/.kube/config

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}AMD GPU + ARC Deployment Script${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""

# Step 1: Check/Install k3s
echo -e "${GREEN}Step 1: Checking k3s...${NC}"
if ! command -v k3s &> /dev/null; then
    echo -e "${YELLOW}k3s not found. Installing...${NC}"
    curl -sfL https://get.k3s.io | sh -
    
    # Set up kubectl
    mkdir -p ~/.kube
    sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
    sudo chown $USER:$USER ~/.kube/config
    
    echo -e "${GREEN}✓ k3s installed${NC}"
else
    echo -e "${GREEN}✓ k3s already installed${NC}"
fi

# Wait for k3s to be ready
echo "Waiting for k3s to be ready..."
for i in {1..30}; do
    if kubectl get nodes > /dev/null 2>&1; then
        break
    fi
    sleep 2
done

if ! kubectl get nodes > /dev/null 2>&1; then
    echo -e "${RED}✗ k3s not responding${NC}"
    exit 1
fi

NODE_NAME=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')
echo -e "${GREEN}✓ k3s ready (node: $NODE_NAME)${NC}"
echo ""

# Step 2: Check/Install Helm
echo -e "${GREEN}Step 2: Checking Helm...${NC}"
if ! command -v helm &> /dev/null; then
    echo -e "${YELLOW}Helm not found. Installing...${NC}"
    
    # Try to install Helm without sudo first (user directory)
    HELM_VERSION="v3.14.0"
    HELM_INSTALL_DIR="$HOME/.local/bin"
    mkdir -p "$HELM_INSTALL_DIR"
    
    # Download Helm binary
    ARCH=$(uname -m)
    case $ARCH in
        x86_64) HELM_ARCH="amd64" ;;
        aarch64|arm64) HELM_ARCH="arm64" ;;
        *) HELM_ARCH="amd64" ;;
    esac
    
    HELM_URL="https://get.helm.sh/helm-${HELM_VERSION}-linux-${HELM_ARCH}.tar.gz"
    
    if curl -fsSL "$HELM_URL" -o /tmp/helm.tar.gz; then
        tar -xzf /tmp/helm.tar.gz -C /tmp
        mv /tmp/linux-${HELM_ARCH}/helm "$HELM_INSTALL_DIR/helm"
        chmod +x "$HELM_INSTALL_DIR/helm"
        rm -rf /tmp/helm.tar.gz /tmp/linux-${HELM_ARCH}
        
        # Add to PATH if not already there
        if [[ ":$PATH:" != *":$HELM_INSTALL_DIR:"* ]]; then
            export PATH="$HELM_INSTALL_DIR:$PATH"
            echo "export PATH=\"$HELM_INSTALL_DIR:\$PATH\"" >> ~/.bashrc
        fi
        
        # Verify helm is now available
        if command -v helm &> /dev/null; then
            echo -e "${GREEN}✓ Helm installed to $HELM_INSTALL_DIR${NC}"
        else
            echo -e "${YELLOW}⚠ Helm installed but not in PATH. Please run: export PATH=\"$HELM_INSTALL_DIR:\$PATH\"${NC}"
        fi
    else
        echo -e "${RED}✗ Failed to download Helm${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Helm already installed${NC}"
fi
echo ""

# Step 3: Install Kyverno
echo -e "${GREEN}Step 3: Installing Kyverno...${NC}"
if ! kubectl get namespace kyverno > /dev/null 2>&1; then
    helm repo add kyverno https://kyverno.github.io/kyverno/ 2>&1 | grep -v "already exists" || true
    helm repo update > /dev/null 2>&1
    
    helm install kyverno kyverno/kyverno \
        --namespace kyverno \
        --create-namespace \
        --set replicaCount=1 \
        > /dev/null 2>&1
    
    echo "Waiting for Kyverno to be ready..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=kyverno -n kyverno --timeout=120s > /dev/null 2>&1
    echo -e "${GREEN}✓ Kyverno installed${NC}"
else
    echo -e "${GREEN}✓ Kyverno already installed${NC}"
fi
echo ""

# Step 4: Install AMD GPU Device Plugin
echo -e "${GREEN}Step 4: Installing AMD GPU Device Plugin...${NC}"
if [ -f "install-amd-gpu-device-plugin.sh" ]; then
    chmod +x install-amd-gpu-device-plugin.sh
    ./install-amd-gpu-device-plugin.sh > /dev/null 2>&1
    
    # Wait a bit for device plugin to register
    sleep 10
    
    GPU_COUNT=$(kubectl get nodes -o jsonpath='{.items[0].status.capacity.amd\.com/gpu}' 2>/dev/null || echo "0")
    if [ "$GPU_COUNT" != "0" ] && [ -n "$GPU_COUNT" ]; then
        echo -e "${GREEN}✓ Device plugin installed (${GPU_COUNT} GPU detected)${NC}"
    else
        echo -e "${YELLOW}⚠ Device plugin installed, but GPU resources not yet visible (may take a moment)${NC}"
    fi
else
    echo -e "${RED}✗ install-amd-gpu-device-plugin.sh not found${NC}"
    exit 1
fi
echo ""

# Step 5: Label GPU Node
echo -e "${GREEN}Step 5: Labeling GPU node...${NC}"
kubectl label nodes "$NODE_NAME" amd.com/gpu.present=true --overwrite > /dev/null 2>&1
echo -e "${GREEN}✓ Node labeled${NC}"
echo ""

# Step 6: Install ARC
echo -e "${GREEN}Step 6: Installing ARC...${NC}"
if [ -f "install-amd-arc.sh" ]; then
    chmod +x install-amd-arc.sh
    ./install-amd-arc.sh \
        --github-url "$GITHUB_URL" \
        --github-pat "$GITHUB_PAT" \
        --node-name "$NODE_NAME" \
        2>&1 | grep -v "already exists" || true
    
    echo -e "${GREEN}✓ ARC installed${NC}"
else
    echo -e "${RED}✗ install-amd-arc.sh not found${NC}"
    exit 1
fi
echo ""

# Step 7: Apply Kyverno GPU Policy
echo -e "${GREEN}Step 7: Applying Kyverno GPU policy...${NC}"
if [ -f "amd-gpu-kyverno-policy.yaml" ]; then
    kubectl apply -f amd-gpu-kyverno-policy.yaml > /dev/null 2>&1
    
    # Wait a moment for policy to be ready
    sleep 3
    
    if kubectl get clusterpolicy inject-amd-gpu-resources > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Kyverno policy applied${NC}"
    else
        echo -e "${RED}✗ Failed to apply Kyverno policy${NC}"
        exit 1
    fi
else
    echo -e "${RED}✗ amd-gpu-kyverno-policy.yaml not found${NC}"
    exit 1
fi
echo ""

# Step 8: Verification
echo -e "${GREEN}Step 8: Verification...${NC}"
echo ""

# Check all components
ALL_GOOD=true

# 1. Kyverno Policy
if kubectl get clusterpolicy inject-amd-gpu-resources > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Kyverno policy: Active"
else
    echo -e "  ${RED}✗${NC} Kyverno policy: Not found"
    ALL_GOOD=false
fi

# 2. Device Plugin
if kubectl get pods -n kube-system -l name=amdgpu-dp-ds --no-headers 2>/dev/null | grep -q Running; then
    echo -e "  ${GREEN}✓${NC} Device plugin: Running"
else
    echo -e "  ${YELLOW}⚠${NC} Device plugin: Not running or not found"
fi

# 3. GPU Resources
GPU_COUNT=$(kubectl get nodes -o jsonpath='{.items[0].status.capacity.amd\.com/gpu}' 2>/dev/null || echo "0")
if [ "$GPU_COUNT" != "0" ] && [ -n "$GPU_COUNT" ]; then
    echo -e "  ${GREEN}✓${NC} GPU resources: ${GPU_COUNT} GPU(s) available"
else
    echo -e "  ${YELLOW}⚠${NC} GPU resources: Not visible yet (may take a moment)"
fi

# 4. Node Label
if kubectl get nodes "$NODE_NAME" -o jsonpath='{.metadata.labels.amd\.com/gpu\.present}' 2>/dev/null | grep -q "true"; then
    echo -e "  ${GREEN}✓${NC} Node label: Set"
else
    echo -e "  ${RED}✗${NC} Node label: Not set"
    ALL_GOOD=false
fi

# 5. ARC Runner
if kubectl get autoscalingrunnersets -n arc-runners > /dev/null 2>&1; then
    RUNNER_NAME=$(kubectl get autoscalingrunnersets -n arc-runners -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ -n "$RUNNER_NAME" ]; then
        echo -e "  ${GREEN}✓${NC} ARC runner: ${RUNNER_NAME}"
    else
        echo -e "  ${YELLOW}⚠${NC} ARC runner: Installed but not ready"
    fi
else
    echo -e "  ${RED}✗${NC} ARC runner: Not found"
    ALL_GOOD=false
fi

echo ""

# Step 9: Optional Test
if [ "$SKIP_TESTS" = false ]; then
    echo -e "${GREEN}Step 9: Running GPU test (optional)...${NC}"
    if [ -f "test-rocm-k3s.yaml" ]; then
        echo "Creating test pod..."
        kubectl apply -f test-rocm-k3s.yaml > /dev/null 2>&1
        
        echo "Waiting for pod to complete..."
        # Wait for pod to be scheduled first
        if kubectl wait --for=condition=Ready pod/rocm-torch-smoke -n arc-runners --timeout=60s > /dev/null 2>&1; then
            # Then wait for pod to complete (phase=Succeeded or phase=Failed)
            echo "Waiting for test to finish..."
            for i in {1..60}; do
                PHASE=$(kubectl get pod rocm-torch-smoke -n arc-runners -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
                if [ "$PHASE" = "Succeeded" ] || [ "$PHASE" = "Failed" ]; then
                    break
                fi
                sleep 2
            done
            
            echo "Checking test results..."
            TEST_LOGS=$(kubectl logs rocm-torch-smoke -n arc-runners 2>&1)
            if echo "$TEST_LOGS" | grep -qi "SUCCESS"; then
                echo -e "  ${GREEN}✓${NC} GPU test: PASSED"
            else
                echo -e "  ${YELLOW}⚠${NC} GPU test: Completed but check logs for details"
                echo "  (Run: kubectl logs rocm-torch-smoke -n arc-runners)"
            fi
            kubectl delete pod rocm-torch-smoke -n arc-runners > /dev/null 2>&1
        else
            echo -e "  ${YELLOW}⚠${NC} GPU test: Pod did not become ready (check manually)"
            kubectl delete pod rocm-torch-smoke -n arc-runners > /dev/null 2>&1
        fi
    else
        echo -e "  ${YELLOW}⚠${NC} test-rocm-k3s.yaml not found, skipping test"
    fi
    echo ""
fi

# Summary
echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}Deployment Summary${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""
echo "Components installed:"
echo "  - k3s Kubernetes"
echo "  - Helm"
echo "  - Kyverno"
echo "  - AMD GPU Device Plugin"
echo "  - Actions Runner Controller (ARC)"
echo "  - Kyverno GPU Policy (with k3s fixes)"
echo ""
echo "Runner label: ${RUNNER_NAME:-amd-arc-runner}"
echo ""
echo "Next steps:"
echo "  1. Update your GitHub workflow to use runner: ${RUNNER_NAME:-amd-arc-runner}"
echo "  2. Test with a workflow run"
echo "  3. Monitor with: kubectl get pods -n arc-runners -w"
echo ""
echo -e "${GREEN}Deployment complete!${NC}"
echo ""

if [ "$ALL_GOOD" = false ]; then
    echo -e "${YELLOW}Note: Some components may need manual verification${NC}"
    exit 1
fi

