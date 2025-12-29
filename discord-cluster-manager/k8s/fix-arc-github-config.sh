#!/bin/bash
#
# Fix ARC GitHub configuration issues
# Usage: ./fix-arc-github-config.sh [--github-url URL] [--github-pat PAT]

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

NAMESPACE_RUNNERS="arc-runners"
INSTALLATION_NAME="amd-arc-runner"
GITHUB_URL=""
GITHUB_PAT=""

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
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${GREEN}=== ARC GitHub Configuration Fix ===${NC}"
echo ""

# Get current config
CURRENT_URL=$(kubectl get autoscalingrunnersets -n arc-runners -o jsonpath='{.items[0].spec.githubConfigUrl}' 2>/dev/null || echo "")

if [ -z "$CURRENT_URL" ]; then
    echo -e "${RED}ERROR: No AutoscalingRunnerSet found${NC}"
    exit 1
fi

echo "Current GitHub URL: $CURRENT_URL"
echo ""

# Remove .git suffix if present and normalize URL
if [ -z "$GITHUB_URL" ]; then
    GITHUB_URL="${CURRENT_URL%.git}"
    echo -e "${YELLOW}Using normalized URL: $GITHUB_URL${NC}"
else
    # Remove .git if user provided it
    GITHUB_URL="${GITHUB_URL%.git}"
fi

# Update the secret if PAT is provided
if [ -n "$GITHUB_PAT" ]; then
    echo "Updating GitHub PAT secret..."
    kubectl create secret generic github-pat-secret \
        --namespace "${NAMESPACE_RUNNERS}" \
        --from-literal=github_token="${GITHUB_PAT}" \
        --dry-run=client -o yaml | kubectl apply -f -
    echo -e "${GREEN}✓ Secret updated${NC}"
else
    echo -e "${YELLOW}Note: Not updating PAT. If you need to update it, run with --github-pat${NC}"
fi

# Update the AutoscalingRunnerSet URL
echo ""
echo "Updating AutoscalingRunnerSet GitHub URL..."

# Use kubectl patch to update the URL
kubectl patch autoscalingrunnersets "${INSTALLATION_NAME}" -n "${NAMESPACE_RUNNERS}" \
    --type='json' \
    -p="[{\"op\": \"replace\", \"path\": \"/spec/githubConfigUrl\", \"value\": \"${GITHUB_URL}\"}]"

echo -e "${GREEN}✓ AutoscalingRunnerSet updated${NC}"
echo ""

echo -e "${YELLOW}=== Important: Check GitHub PAT Permissions ===${NC}"
echo ""
echo "Your GitHub PAT must have these scopes:"
echo "  - repo (Full control of private repositories)"
echo "  - read:org (Read org membership) [if using org runners]"
echo ""
echo "To check/update your PAT:"
echo "  1. Go to: https://github.com/settings/tokens"
echo "  2. Find your token or create a new one"
echo "  3. Ensure 'repo' scope is checked"
echo "  4. Update the secret:"
echo "     kubectl create secret generic github-pat-secret \\"
echo "       --namespace arc-runners \\"
echo "       --from-literal=github_token=YOUR_NEW_TOKEN \\"
echo "       --dry-run=client -o yaml | kubectl apply -f -"
echo ""
echo "Waiting 10 seconds for ARC to reconcile..."
sleep 10

echo ""
echo "Checking ARC controller logs for errors..."
kubectl logs -n arc-systems -l app.kubernetes.io/name=gha-runner-scale-set-controller --tail=20 2>&1 | grep -i "error\|404\|403" || echo "No obvious errors in recent logs"

echo ""
echo -e "${GREEN}Done! Check the runner scale set status:${NC}"
echo "  kubectl get autoscalingrunnersets -n arc-runners"
echo "  kubectl get pods -n arc-runners"

