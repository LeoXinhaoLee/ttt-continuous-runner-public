# Creating a User Account for GitHub Actions Runner

If you're logged in as root, you need to create a non-root user account to run the GitHub Actions runner.

## Option 1: Create a Dedicated User for the Runner (Recommended)

### Step 1: Create the user

```bash
# Create a new user (replace 'runner' with your preferred username)
sudo adduser runner

# Or without interactive prompts:
sudo adduser --disabled-password --gecos "" runner
```

### Step 2: Add user to necessary groups

```bash
# Add to docker group (if Docker is installed)
sudo usermod -aG docker runner

# Add to groups that might be needed for GPU access
sudo usermod -aG render,video runner  # For AMD GPU access
```

### Step 3: Switch to the new user

```bash
# Switch to the new user
su - runner

# Or use sudo to run commands as that user
sudo -u runner -i
```

### Step 4: Run the setup script as the new user

```bash
cd /root/ttt-continuous-main/cudaLLM/discord-cluster-manager
./scripts/setup_github_runner_mla_decode.sh
```

## Option 2: Use an Existing User Account

If you already have a non-root user account:

```bash
# Switch to that user
su - username

# Or
sudo -u username -i
```

## Option 3: Temporarily Disable the Sudo Check (Not Recommended)

If you absolutely must run as root (not recommended), you can temporarily modify the script to skip the check, but this may cause issues with the runner installation.

## Notes

- The runner will be installed in the user's home directory: `~/.actions-runner-amd-docker` or `$HOME/actions-runner-amd-docker`
- The user needs access to Docker if you're using containers
- The user needs to be able to access GPU devices (usually via group memberships)
- You can always use `sudo` for specific commands if the user needs elevated privileges

## Verifying User Setup

```bash
# Check current user
whoami

# Should NOT be 'root'

# Check user groups
groups

# Should include groups like: docker, render, video (if applicable)
```

