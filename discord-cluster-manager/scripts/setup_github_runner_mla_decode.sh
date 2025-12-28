#!/bin/bash
#
# Setup script for GitHub Actions runner for mla-decode
# This script automates the steps needed to set up a GitHub Actions runner
# that uses the amd-docker.Dockerfile container environment for mla-decode evals.
#
# Usage:
#   ./scripts/setup_github_runner_mla_decode.sh
#
# Prerequisites:
#   - GitHub repository with Actions enabled
#   - GitHub token with workflow permissions
#   - Docker installed on the runner machine
#   - AMD GPU with ROCm support (for AMD runners)

set -e

# Check if running with sudo and exit if so
if [ "$EUID" -eq 0 ]; then
    echo "ERROR: This script must NOT be run with sudo or as root."
    echo "The GitHub Actions runner should be installed as a regular user."
    echo "Please run this script without sudo."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Get repo root (two levels up from script: scripts -> discord-cluster-manager -> repo root)
REPO_ROOT="$(cd "$PROJECT_ROOT/.." && pwd)"
cd "$PROJECT_ROOT"

echo "========================================="
echo "GitHub Runner Setup for mla-decode"
echo "========================================="
echo ""

# Step 1: Build and publish the Docker image
echo "Step 1: Building and publishing AMD Docker image..."
echo "NOTE: This step is OPTIONAL on the GPU instance."
echo "The Docker image can be built via GitHub Actions workflow (repo root: .github/workflows/publish_amd_docker.yml)"
echo "or built on any machine with Docker installed."
echo ""
read -p "Do you want to build the Docker image here? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Building Docker image locally..."
    echo "Note: To publish to ghcr.io, you'll need to:"
    echo "  1. Login to ghcr.io: echo \$GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin"
    echo "  2. Build: docker build -f docker/amd-docker.Dockerfile -t ghcr.io/gpu-mode/amd-runner:latest ."
    echo "  3. Push: docker push ghcr.io/gpu-mode/amd-runner:latest"
    echo ""
    echo "Alternatively, trigger the GitHub Actions workflow to build and publish automatically."
    echo ""
fi

# Step 2: Set up self-hosted GitHub Actions runner
echo "Step 2: Setting up self-hosted GitHub Actions runner"
echo "⚠️  IMPORTANT: This step MUST be run on the AMD GPU instance!"
echo "This is where workflows will execute, so the runner needs direct GPU access."
echo ""
echo "This requires:"
echo "  1. GitHub repository in format: owner/repo (e.g., mertyg/ttt-continuous)"
echo "  2. Admin access to the repository (or be the owner)"
echo "  3. GitHub personal access token with 'repo' and 'workflow' scopes"
echo "  4. Runner name (should match the 'runner' input in workflow, e.g., 'amd-docker')"
echo ""
echo "Note: You need ADMIN access to the repository (not just Write access)"
echo "      Check at: https://github.com/OWNER/REPO/settings/access"
echo ""
read -p "Do you want to set up a new runner? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # read -p "Enter GitHub repository (owner/repo): " GITHUB_REPO
    # read -p "Enter GitHub personal access token: " GITHUB_TOKEN
    # read -p "Enter runner name (e.g., amd-docker): " RUNNER_NAME
    GITHUB_REPO=
    GITHUB_TOKEN=
    RUNNER_NAME="amd-docker"
    
    echo ""
    echo "Validating inputs before installation..."
    
    # Validate repository format
    if [[ ! "$GITHUB_REPO" =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$ ]]; then
        echo "❌ ERROR: Invalid repository format: $GITHUB_REPO"
        echo "   Repository must be in format: owner/repo"
        echo "   Examples: mertyg/ttt-continuous, github/actions-runner"
        echo "   Do NOT include: https://, .git, or git@github.com:"
        exit 1
    fi
    
    # Extract owner and repo name
    REPO_OWNER=$(echo "$GITHUB_REPO" | cut -d'/' -f1)
    REPO_NAME=$(echo "$GITHUB_REPO" | cut -d'/' -f2)
    
    echo "✓ Repository format valid: $REPO_OWNER/$REPO_NAME"
    
    # Test token validity and repository access
    echo "Testing token and repository access..."
    REPO_RESPONSE=$(curl -s -w "\n%{http_code}" -H "Authorization: token $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github.v3+json" \
        "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME")
    
    HTTP_CODE=$(echo "$REPO_RESPONSE" | tail -n1)
    REPO_BODY=$(echo "$REPO_RESPONSE" | sed '$d')
    
    if [ "$HTTP_CODE" = "404" ]; then
        echo "❌ ERROR: Repository not found or you don't have access"
        echo "   Repository: $REPO_OWNER/$REPO_NAME"
        echo "   Check: https://github.com/$REPO_OWNER/$REPO_NAME"
        exit 1
    elif [ "$HTTP_CODE" = "401" ]; then
        echo "❌ ERROR: Authentication failed - token is invalid or expired"
        echo "   Generate a new token at: https://github.com/settings/tokens"
        exit 1
    elif [ "$HTTP_CODE" = "403" ]; then
        echo "❌ ERROR: Access forbidden - token may not have sufficient permissions"
        echo "   Required scopes: 'repo' and 'workflow'"
        exit 1
    elif [ "$HTTP_CODE" != "200" ]; then
        echo "❌ ERROR: Unexpected response from GitHub API (HTTP $HTTP_CODE)"
        exit 1
    fi
    
    echo "✓ Repository access confirmed"
    
    # Check if Actions is enabled and get registration token
    echo "Checking if GitHub Actions is enabled and getting registration token..."
    REG_TOKEN_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Authorization: token $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github.v3+json" \
        "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/actions/runners/registration-token")
    
    REG_TOKEN_HTTP_CODE=$(echo "$REG_TOKEN_RESPONSE" | tail -n1)
    REG_TOKEN_BODY=$(echo "$REG_TOKEN_RESPONSE" | sed '$d')
    
    if [ "$REG_TOKEN_HTTP_CODE" = "404" ]; then
        echo ""
        echo "❌ ERROR: GitHub Actions is not enabled for this repository"
        echo ""
        echo "To enable GitHub Actions:"
        echo "  1. Go to: https://github.com/$REPO_OWNER/$REPO_NAME/settings/actions"
        echo "  2. Under 'Actions permissions', select 'Allow all actions and reusable workflows'"
        echo "  3. Under 'Workflow permissions', select 'Read and write permissions'"
        echo "  4. Click 'Save'"
        echo ""
        echo "For organization repositories, you may also need to:"
        echo "  - Go to: https://github.com/organizations/$REPO_OWNER/settings/actions"
        echo "  - Enable Actions at the organization level"
        echo ""
        exit 1
    elif [ "$REG_TOKEN_HTTP_CODE" = "403" ]; then
        echo "❌ ERROR: Access forbidden to runner registration"
        echo "   You need ADMIN access to the repository (not just Write)"
        echo "   Check: https://github.com/$REPO_OWNER/$REPO_NAME/settings/access"
        exit 1
    elif [ "$REG_TOKEN_HTTP_CODE" != "201" ] && [ "$REG_TOKEN_HTTP_CODE" != "200" ]; then
        echo "❌ ERROR: Unexpected response from registration endpoint (HTTP $REG_TOKEN_HTTP_CODE)"
        echo "   Response: $REG_TOKEN_BODY"
        exit 1
    fi
    
    # Extract the registration token from the response
    # Try using jq if available (most reliable), otherwise use grep+sed
    if command -v jq >/dev/null 2>&1; then
        REGISTRATION_TOKEN=$(echo "$REG_TOKEN_BODY" | jq -r '.token' 2>/dev/null)
    fi
    
    # Fallback: extract token using grep+sed (handles whitespace/newlines in JSON)
    if [ -z "$REGISTRATION_TOKEN" ] || [ "$REGISTRATION_TOKEN" = "null" ]; then
        REGISTRATION_TOKEN=$(echo "$REG_TOKEN_BODY" | grep -o '"token"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
    fi
    
    if [ -z "$REGISTRATION_TOKEN" ] || [ "$REGISTRATION_TOKEN" = "null" ]; then
        echo "❌ ERROR: Failed to extract registration token from API response"
        echo "   Response: $REG_TOKEN_BODY"
        echo ""
        echo "   Tip: Install 'jq' for better JSON parsing: sudo apt-get install jq"
        exit 1
    fi
    
    echo "✓ GitHub Actions is enabled and accessible"
    echo "✓ Registration token obtained (expires in 1 hour)"
    echo "✓ All pre-flight checks passed!"
    echo ""
    
    echo "Installing GitHub Actions runner..."
    
    # Create a directory for the runner
    RUNNER_DIR="$HOME/actions-runner-$RUNNER_NAME"
    if [ -d "$RUNNER_DIR" ]; then
        echo "Warning: Directory $RUNNER_DIR already exists"
        read -p "Do you want to remove it and start fresh? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$RUNNER_DIR"
        else
            echo "Skipping runner installation"
            exit 1
        fi
    fi
    
    mkdir -p "$RUNNER_DIR"
    cd "$RUNNER_DIR"
    
    # Download the latest runner package
    echo "Downloading latest runner package..."
    LATEST_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep tag_name | cut -d '"' -f 4)
    RUNNER_VERSION=${LATEST_VERSION#v}
    RUNNER_ARCH="x64"
    
    curl -o actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz -L https://github.com/actions/runner/releases/download/${LATEST_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz
    
    # Extract the installer
    tar xzf ./actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz
    
    # Configure the runner
    echo "Configuring runner..."
    echo "Attempting to configure runner for: https://github.com/$GITHUB_REPO"
    echo "Runner name: $RUNNER_NAME"
    echo ""
    echo "Using registration token (expires in 1 hour)..."
    ./config.sh --url "https://github.com/$GITHUB_REPO" --token "$REGISTRATION_TOKEN" --name "$RUNNER_NAME" --work "_work" --labels "$RUNNER_NAME,amd,rocm,self-hosted" --replace
    
    echo ""
    echo "Runner configured successfully!"
    echo ""
    echo "To start the runner, run:"
    echo "  cd $RUNNER_DIR"
    echo "  ./run.sh"
    echo ""
    echo "Or install it as a service:"
    echo "  sudo ./svc.sh install"
    echo "  sudo ./svc.sh start"
    echo ""
    
    cd "$PROJECT_ROOT"
fi

# Step 3: Verify workflow file exists
echo "Step 3: Verifying workflow file exists..."
# GitHub Actions only uses workflows from the root .github/ folder, not nested ones
WORKFLOW_FILE="$REPO_ROOT/.github/workflows/amd-mla-decode-workflow.yml"
if [ -f "$WORKFLOW_FILE" ]; then
    echo "✓ Workflow file found: $WORKFLOW_FILE"
else
    echo "✗ Workflow file not found: $WORKFLOW_FILE"
    echo "  Please ensure the workflow file is created in the repository root."
    exit 1
fi

# Step 4: Verify Dockerfile exists
echo "Step 4: Verifying Dockerfile exists..."
DOCKERFILE="docker/amd-docker.Dockerfile"
if [ -f "$DOCKERFILE" ]; then
    echo "✓ Dockerfile found: $DOCKERFILE"
else
    echo "✗ Dockerfile not found: $DOCKERFILE"
    exit 1
fi

# Step 5: Check Docker permissions
echo "Step 5: Checking Docker permissions..."
if command -v docker >/dev/null 2>&1; then
    echo "✓ Docker is installed"
    
    # Check if user can access Docker
    if docker version >/dev/null 2>&1; then
        echo "✓ Docker access is working (user has permission to use Docker)"
    else
        echo ""
        echo "⚠️  WARNING: Cannot access Docker daemon!"
        echo "   Error: permission denied while trying to connect to the docker API at unix:///var/run/docker.sock"
        echo ""
        echo "   This is REQUIRED for the workflow to run (it uses container: in the workflow)."
        echo ""
        echo "   To fix this, add your user to the docker group:"
        echo "     sudo usermod -aG docker $USER"
        echo ""
        echo "   After adding yourself to the docker group, you MUST:"
        echo "     1. Log out and log back in, OR"
        echo "     2. Restart the runner service if it's already running:"
        echo "        sudo systemctl stop actions.runner.\$RUNNER_NAME.service"
        echo "        sudo systemctl start actions.runner.\$RUNNER_NAME.service"
        echo ""
        echo "   Note: The group change won't take effect until you log out/in or restart the service."
        echo ""
        read -p "Do you want to add yourself to the docker group now? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Adding user $USER to docker group..."
            if sudo usermod -aG docker "$USER"; then
                echo "✓ Successfully added $USER to docker group"
                echo ""
                echo "⚠️  IMPORTANT: You must log out and log back in for this change to take effect!"
                echo "   Or restart the runner service if it's already running as a systemd service."
                echo ""
                echo "   After logging back in, verify with: docker version"
            else
                echo "❌ ERROR: Failed to add user to docker group"
                exit 1
            fi
        else
            echo "⚠️  Skipping Docker group setup. You'll need to do this manually before the runner can work."
            echo ""
        fi
    fi
else
    echo "⚠️  WARNING: Docker is not installed or not in PATH"
    echo "   The workflow requires Docker to run containers."
    echo "   Install Docker with: sudo apt-get update && sudo apt-get install -y docker.io"
    echo "   Then add your user to the docker group: sudo usermod -aG docker $USER"
fi

# Step 6: Verify mla-decode task files
echo "Step 6: Verifying mla-decode task files..."
TASK_DIR="src/mla-decode"
if [ -d "$TASK_DIR" ]; then
    echo "✓ mla-decode task directory found: $TASK_DIR"
    if [ -f "$TASK_DIR/task.yml" ]; then
        echo "✓ task.yml found"
    else
        echo "✗ task.yml not found in $TASK_DIR"
    fi
else
    echo "✗ mla-decode task directory not found: $TASK_DIR"
    exit 1
fi

# Step 7: Environment variables check
echo ""
echo "Step 7: Required environment variables"
echo "The following environment variables should be set (in .env or environment):"
echo "  - GITHUB_TOKEN: GitHub personal access token with 'repo' and 'workflow' scopes"
echo "  - GITHUB_REPO: GitHub repository (e.g., owner/repo)"
echo "  - GITHUB_WORKFLOW_BRANCH: Branch to use for workflows (default: main)"
echo ""
echo "To set these, create a .env file in the project root:"
echo "  GITHUB_TOKEN=your_token_here"
echo "  GITHUB_REPO=your-org/your-repo"
echo "  GITHUB_WORKFLOW_BRANCH=main"

echo ""
echo "========================================="
echo "Setup Summary"
echo "========================================="
echo ""
echo "What to run WHERE:"
echo ""
echo "ON THIS AMD GPU INSTANCE (where execution happens):"
echo "  ✓ Step 2: Set up the self-hosted runner (REQUIRED here)"
echo "  ✓ Step 5: Add user to docker group and log out/in (REQUIRED for container workflows)"
echo "  ✓ Step 6: Verify mla-decode task files exist"
echo "  ✓ Start the runner service: cd \$HOME/actions-runner-amd-docker && ./run.sh"
echo "    Or install as service: sudo ./svc.sh install && sudo ./svc.sh start"
echo ""
echo "ANYWHERE (can be done via GitHub Actions or on any machine):"
echo "  - Step 1: Build and publish Docker image (via repo root: .github/workflows/publish_amd_docker.yml)"
echo ""
echo "Next steps:"
echo "  1. If you were added to the docker group, LOG OUT AND LOG BACK IN (required for group changes)"
echo "  2. Verify Docker access: docker version (should work without sudo)"
echo "  3. Ensure the Docker image is built and published (ghcr.io/leoxinhaolee/amd-runner:latest)"
echo "  4. Ensure the runner is running: check with 'ps aux | grep Runner.Listener'"
echo "  5. Test the workflow from another machine by running:"
echo "     uv run python src/run_mla_decode_github.py --submission path/to/submission.py"
echo ""
echo "For more information, see:"
echo "  - README.md"
echo "  - docs/ directory"
echo ""

