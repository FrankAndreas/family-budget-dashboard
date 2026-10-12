# GitHub CI/CD Pipeline Documentation

## Overview

The Family Budget Dashboard uses GitHub Actions for continuous integration and deployment. The pipeline includes testing, linting, security scanning, Docker image building, and automated deployment.

## Workflows

### 1. Main CI/CD Pipeline (`ci-cd.yml`)

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop`
- Release creation

**Jobs:**

#### Backend Testing & Linting
- ✅ Code formatting check (Black)
- ✅ Linting (Flake8)
- ✅ Type checking (MyPy)
- ✅ Unit tests (Pytest)
- ✅ Code coverage report

#### Frontend Testing & Linting
- ✅ ESLint checks
- ✅ TypeScript compilation
- ✅ Build verification
- ✅ Artifact upload

#### Security Scanning
- ✅ Trivy vulnerability scanner
- ✅ Dependency security checks
- ✅ SARIF report upload to GitHub Security

#### Build & Push Docker Images
- ✅ Multi-platform builds (amd64, arm64)
- ✅ Push to GitHub Container Registry
- ✅ Semantic versioning tags
- ✅ Build provenance attestation

#### Integration Tests
- ✅ Pull and test built images
- ✅ Full stack integration testing
- ✅ API endpoint validation

#### Deployment
- ✅ Automated deployment to production (main branch only)
- ✅ Environment protection rules
- ✅ Deployment notifications

### 2. Pull Request Checks (`pr-checks.yml`)

**Triggers:**
- Pull request opened, synchronized, or reopened

**Checks:**
- ✅ Semantic PR title validation
- ✅ Large file detection
- ✅ Secret scanning (TruffleHog)
- ✅ Docker Compose validation
- ✅ Code quality checks
- ✅ Documentation updates

### 3. Release Workflow (`release.yml`)

**Triggers:**
- Git tags matching `v*.*.*` pattern

**Actions:**
- ✅ Automatic changelog generation
- ✅ GitHub Release creation
- ✅ Tagged Docker images
- ✅ Release notes with Docker pull commands

## Docker Images

### Image Naming Convention

```
ghcr.io/YOUR-USERNAME/family-budget-dashboard/backend:TAG
ghcr.io/YOUR-USERNAME/family-budget-dashboard/frontend:TAG
```

### Available Tags

- `latest` - Latest build from main branch
- `develop` - Latest build from develop branch
- `v1.0.0` - Specific version tag
- `main-abc123` - Commit SHA on main branch

### Pulling Images

```bash
# Latest version
docker pull ghcr.io/YOUR-USERNAME/family-budget-dashboard/backend:latest
docker pull ghcr.io/YOUR-USERNAME/family-budget-dashboard/frontend:latest

# Specific version
docker pull ghcr.io/YOUR-USERNAME/family-budget-dashboard/backend:v1.0.0
docker pull ghcr.io/YOUR-USERNAME/family-budget-dashboard/frontend:v1.0.0
```

## Setup Instructions

### 1. Enable GitHub Container Registry

1. Go to your repository settings
2. Navigate to "Actions" → "General"
3. Under "Workflow permissions", select "Read and write permissions"
4. Check "Allow GitHub Actions to create and approve pull requests"

### 2. Configure Secrets (Optional)

For deployment, add these secrets in repository settings:

```
DEPLOY_HOST - Production server hostname
DEPLOY_USER - SSH username
DEPLOY_KEY - SSH private key
```

### 3. Enable Dependabot

Dependabot is configured to automatically update dependencies weekly. No additional setup required.

### 4. Branch Protection Rules

Recommended branch protection for `main`:

- ✅ Require pull request reviews (1+ approvals)
- ✅ Require status checks to pass
  - `backend-test`
  - `frontend-test`
  - `security-scan`
- ✅ Require branches to be up to date
- ✅ Include administrators

## Local Testing

### Test the CI pipeline locally

```bash
# Install act (GitHub Actions local runner)
# https://github.com/nektos/act

# Run the workflow
act push

# Run specific job
act -j backend-test

# Run with secrets
act -s GITHUB_TOKEN=your_token
```

### Run linting locally

```bash
# Backend
cd backend
black app/
flake8 app/ --max-line-length=120
mypy app/ --ignore-missing-imports

# Frontend
cd frontend
npm run lint
npx tsc --noEmit
```

## Monitoring

### Build Status

Check build status at:
```
https://github.com/YOUR-USERNAME/family-budget-dashboard/actions
```

### Container Registry

View published images at:
```
https://github.com/YOUR-USERNAME/family-budget-dashboard/pkgs/container/family-budget-dashboard
```

### Security Alerts

View security alerts at:
```
https://github.com/YOUR-USERNAME/family-budget-dashboard/security
```

## Deployment

### Automatic Deployment

Pushes to `main` branch automatically deploy to production (if configured).

### Manual Deployment

```bash
# SSH to production server
ssh user@production-server

# Pull latest images
docker pull ghcr.io/YOUR-USERNAME/family-budget-dashboard/backend:latest
docker pull ghcr.io/YOUR-USERNAME/family-budget-dashboard/frontend:latest

# Update and restart
cd /opt/family-budget-dashboard
docker compose pull
docker compose up -d
```

### Rollback

```bash
# Revert to previous version
docker pull ghcr.io/YOUR-USERNAME/family-budget-dashboard/backend:v1.0.0
docker pull ghcr.io/YOUR-USERNAME/family-budget-dashboard/frontend:v1.0.0

docker compose up -d
```

## Release Process

### Creating a Release

1. **Update version** in relevant files
2. **Commit changes** to main branch
3. **Create and push tag:**
   ```bash
   git tag -a v1.0.0 -m "Release version 1.0.0"
   git push origin v1.0.0
   ```
4. **GitHub Actions** will automatically:
   - Run all tests
   - Build Docker images
   - Create GitHub Release
   - Generate changelog
   - Tag images with version

### Version Numbering

Follow [Semantic Versioning](https://semver.org/):

- `v1.0.0` - Major.Minor.Patch
- `v1.1.0` - New features (backward compatible)
- `v1.0.1` - Bug fixes
- `v2.0.0` - Breaking changes

## Troubleshooting

### Build Failures

**Issue**: Tests fail in CI but pass locally

**Solutions**:
- Check service startup timing (add sleep if needed)
- Verify environment variables
- Check Docker Compose configuration

**Issue**: Docker build fails

**Solutions**:
- Verify Dockerfile syntax
- Check base image availability
- Review build logs for specific errors

### Permission Issues

**Issue**: Cannot push to GitHub Container Registry

**Solutions**:
- Verify workflow permissions in repository settings
- Check GITHUB_TOKEN has package write permissions
- Ensure repository visibility allows package publishing

### Deployment Issues

**Issue**: Deployment fails

**Solutions**:
- Verify secrets are configured
- Check SSH connectivity
- Review deployment logs
- Verify server has Docker installed

## Best Practices

1. **Always create PRs** for changes
2. **Wait for CI checks** before merging
3. **Review security alerts** regularly
4. **Keep dependencies updated** (Dependabot)
5. **Tag releases** for production deployments
6. **Monitor build times** and optimize if needed
7. **Use semantic commit messages**

## Metrics

Current pipeline performance:

- ⏱️ **Backend tests**: ~30s
- ⏱️ **Frontend tests**: ~45s
- ⏱️ **Docker build**: ~2-3min
- ⏱️ **Total pipeline**: ~5-7min

## Support

For issues with the CI/CD pipeline:

1. Check [GitHub Actions documentation](https://docs.github.com/en/actions)
2. Review workflow logs in the Actions tab
3. Open an issue in the repository

---

**Last Updated**: January 20, 2026  
**Pipeline Version**: 1.0  
**Maintained By**: Your Team
