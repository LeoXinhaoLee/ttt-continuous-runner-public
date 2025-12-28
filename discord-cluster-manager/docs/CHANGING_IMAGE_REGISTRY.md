# Changing Docker Image Registry Location

To change where the AMD runner Docker image is published, update the following files:

## 1. Update the Publish Workflow

Edit `.github/workflows/publish_amd_docker.yml`:

```yaml
env:
  # Change REGISTRY to your container registry
  # Examples:
  #   - ghcr.io (GitHub Container Registry)
  #   - docker.io (Docker Hub)
  #   - quay.io (Red Hat Quay)
  #   - your-registry.com (Private registry)
  REGISTRY: ghcr.io
  
  # Change IMAGE_NAME to your desired image name
  # Format: owner/repository or just repository
  # Examples:
  #   - gpu-mode/amd-runner
  #   - your-org/amd-runner
  #   - my-custom-amd-runner
  IMAGE_NAME: gpu-mode/amd-runner
```

**For Docker Hub:**
```yaml
env:
  REGISTRY: docker.io
  IMAGE_NAME: your-dockerhub-username/amd-runner
```

**For private registry:**
```yaml
env:
  REGISTRY: registry.example.com
  IMAGE_NAME: your-namespace/amd-runner
```

## 2. Update the Workflow that Uses the Image

Edit `.github/workflows/amd-mla-decode-workflow.yml`:

Change the `image` field in the `container` section to match your new registry:

```yaml
container:
  image: YOUR_REGISTRY/YOUR_IMAGE_NAME:latest
  options: --privileged
```

**Example for Docker Hub:**
```yaml
container:
  image: docker.io/your-username/amd-runner:latest
  options: --privileged
```

**Example for private registry:**
```yaml
container:
  image: registry.example.com/your-namespace/amd-runner:latest
  options: --privileged
```

## 3. Update Authentication Secrets

Depending on your registry, you may need to update the authentication:

### For GitHub Container Registry (ghcr.io):
- Secret name: `PUBLISH_TOKEN`
- Use a GitHub Personal Access Token (PAT) with `write:packages` permission

### For Docker Hub:
- Update the login action in `publish_amd_docker.yml`:
  ```yaml
  - name: Log in to Docker Hub
    uses: docker/login-action@v2
    with:
      username: ${{ secrets.DOCKERHUB_USERNAME }}
      password: ${{ secrets.DOCKERHUB_TOKEN }}
  ```
- Add secrets: `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`

### For Private Registry:
- Update the login action:
  ```yaml
  - name: Log in to Container Registry
    uses: docker/login-action@v2
    with:
      registry: ${{ env.REGISTRY }}
      username: ${{ secrets.REGISTRY_USERNAME }}
      password: ${{ secrets.REGISTRY_PASSWORD }}
  ```
- Add secrets: `REGISTRY_USERNAME` and `REGISTRY_PASSWORD`

## 4. Update Documentation/Comments

Update any references in:
- `scripts/setup_github_runner_mla_decode.sh` (lines mentioning the image name)
- `src/run_mla_decode_github.py` (docstring mentioning the image)

## Summary

The image location is controlled by:
- **Where it's published**: `.github/workflows/publish_amd_docker.yml` (REGISTRY and IMAGE_NAME env vars)
- **Where it's used**: `.github/workflows/amd-mla-decode-workflow.yml` (container.image field)

Make sure both match!

