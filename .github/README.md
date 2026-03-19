# GitHub Actions Workflows

This directory contains GitHub Actions workflows that automate tasks for the JukePlayer backend.

## Available Workflows

### Build and Push Docker Image (`build-docker-image.yml`)

Automatically builds and pushes the JukePlayer Docker image to GitHub Container Registry (GHCR) when code is pushed to the main branch.

#### Trigger Conditions:
- ✅ Push to `main` branch
- ✅ Changes in `app/`, `requirements.txt`, or `run.py`
- ✅ Changes in `Dockerfile`
- ✅ Manual trigger via GitHub Actions UI

#### What it does:
1. Checks out the repository
2. Sets up Docker Buildx for multi-platform builds
3. Authenticates with GitHub Container Registry
4. Extracts image metadata and tags
5. Builds the Docker image
6. Pushes to `ghcr.io/{owner}/jukeplayer-jukeplayer`

#### Image Tags:
- `latest` - Always points to the latest build on main branch
- `main-{commit-sha}` - Specific commit reference
- `v{version}` - Semantic version tags (if using releases)

#### View Built Images:
1. Go to **Packages** on GitHub repository page
2. Look for `jukeplayer` package
3. Click to see all image tags and commits

#### Pull the Built Image:
```bash
docker pull ghcr.io/{owner}/jukeplayer-jukeplayer:latest
```

## Setup Instructions

### No Additional Setup Required!

The workflow uses GitHub's built-in `GITHUB_TOKEN` which is automatically available during Actions runs. Your repository needs to have **Packages** enabled (default for all repositories).

### Optional: Fine-tune the workflow

Edit `.github/workflows/build-docker-image.yml` to:

**Change trigger branches:**
```yaml
on:
  push:
    branches:
      - main
      - develop  # Add more branches here
```

**Add pull request builds (for testing):**
```yaml
on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main
```

**Only build on version tags:**
```yaml
on:
  push:
    tags:
      - 'v*'
```

## Using the Built Image in Docker Compose

Once the image is built, you can reference it in your docker-compose.yml:

```yaml
jukeplayer:
  image: ghcr.io/{owner}/jukeplayer-jukeplayer:latest
  # ... rest of config
```

To use a specific build:
```yaml
jukeplayer:
  image: ghcr.io/{owner}/jukeplayer-jukeplayer:main-abc123def456
  # ... rest of config
```

## Troubleshooting

### Workflow not triggering?
- Check that changes are in the `app/` directory or core files
- Verify the commit is being pushed to the `main` branch
- Check the **Actions** tab for any errors

### Build failures?
1. Click on the failed workflow run
2. Expand the "Build and push Docker image" step
3. Look at the error logs
4. Common issues:
   - Missing `requirements.txt`
   - Dockerfile syntax errors
   - Invalid base image

### Image not pushed to GHCR?
- Check that you have the correct repository permissions
- Verify the workflow has `packages: write` permission (it should)
- Try manually triggering via Actions → run workflow

### How to manually trigger a build:
1. Go to **Actions** tab in GitHub
2. Select **Build and Push Docker Image** workflow
3. Click **Run workflow**
4. Choose branch and click **Run workflow**

## Security Notes

- The `GITHUB_TOKEN` is automatically scoped and expires after the workflow completes
- Image tags are public (anyone can pull them)
- For private images, you'd need to set up a private registry

## Next Steps

- Set up automatic deployments using the built images
- Add image signing for security
- Configure image retention policies
- Add container scanning for vulnerabilities

## More Information

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Build and Push Action](https://github.com/docker/build-push-action)
- [GitHub Container Registry Documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
