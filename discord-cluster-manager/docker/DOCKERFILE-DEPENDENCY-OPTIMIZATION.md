# Docker Image Dependency Optimization

## Changes Made

To speed up workflow runs, we've pre-installed `requirements-dev.txt` dependencies in the Docker image.

### Updated Files

1. **`docker/amd-docker.Dockerfile`**
   - Added installation of all `requirements-dev.txt` dependencies at the end of the Dockerfile
   - These dependencies are now baked into the image

2. **`.github/workflows/amd-mla-decode-workflow-ARC.yml`**
   - Added comments explaining dependencies are pre-installed
   - Added `--upgrade-strategy only-if-needed` to pip install for requirements-dev.txt
   - Removed `--privileged` from container options (GPU isolation handled by Kyverno policy)

## How It Works

1. **Docker Build Time**: All `requirements-dev.txt` dependencies are installed in the image
2. **Workflow Run Time**: 
   - `pip install -r requirements-dev.txt` will skip already-installed packages (very fast)
   - Only new/updated packages will be installed
   - Dynamic `requirements.txt` (from workflow input) still needs to be installed
   - `pip install -e .` still runs (needs source code from checkout)

## Performance Impact

**Before**: Installing all dependencies from `requirements-dev.txt` could take 1-2 minutes

**After**: Most dependencies already installed, pip skips them → workflow step should complete in seconds

## What Still Gets Installed at Runtime

1. ✅ **Dynamic `requirements.txt`** - User-provided via workflow input (can't pre-install)
2. ✅ **Package itself (`pip install -e .`)** - Needs source code from checkout (can't pre-install)

## Next Steps

1. **Rebuild the Docker image**:
   ```bash
   # Option 1: Via GitHub Actions workflow
   # Trigger: .github/workflows/publish_amd_docker.yml
   
   # Option 2: Manual build
   docker build -f docker/amd-docker.Dockerfile -t ghcr.io/leoxinhaolee/amd-runner:latest .
   docker push ghcr.io/leoxinhaolee/amd-runner:latest
   ```

2. **After pushing new image**, workflow runs will automatically use it and be faster

## Maintenance

If `requirements-dev.txt` changes:
1. Update the Dockerfile to match
2. Rebuild and push the image
3. Workflow runs will automatically use the new image

The workflow step will still install requirements-dev.txt (in case there are updates), but it will be much faster since most packages are already installed.

