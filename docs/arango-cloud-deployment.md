# Deploying AOE on ArangoDB Cloud Container Management

## Overview

Arango-OntoExtract (AOE) is designed to deploy alongside an ArangoDB Cloud deployment using ArangoCD's Container Management Service. This guide covers both cloud and standalone deployment options.

> **Two deployment paths exist — pick one per environment.**
>
> | Path | Use when | Documented in |
> |------|----------|--------------|
> | **Unified Docker image** (this doc) | You have an OCI registry and want a single image that bundles nginx + Next + Python | `docs/arango-cloud-deployment.md` (here) |
> | **Manual packaging** (`.tar.gz` + `py13base` + `uv`) | Your platform is the **Arango Container Manager** with `py13base`, and you want operations to mirror how Arango itself ships services | [`docs/container-manager-deployment.md`](./container-manager-deployment.md) |
>
> Both paths share the same `Settings`, migrations, and frontend code; they
> differ only in how the bundle is built and how the frontend is served. If
> your environment sits behind a path-prefix ingress (e.g. BYOC under
> `/_service/uds/_db/<db>/<svc>`), also read
> [`docs/path-prefix-routing.md`](./path-prefix-routing.md).

## Prerequisites

- Active ArangoDB Cloud account
- ArangoCD deployment running (ArangoDB 3.12+)
- API keys for LLM providers (Anthropic and/or OpenAI)
- Docker installed locally (for building images)

---

## Option A: ArangoCD Container Management

### 1. Build and Push Image

Build the unified AOE image and push it to your preferred container registry:

```bash
docker build -t registry.example.com/aoe:latest .
docker push registry.example.com/aoe:latest
```

**Recommended image tags:**
- `aoe:latest` — latest development
- `aoe:1.0.0` — specific version
- `aoe:main` — main branch

### 2. Add Container in ArangoCD

1. Navigate to your deployment → **"Containers"** tab
2. Click **"Add Container"**
3. Configure the following settings:

| Field | Value | Notes |
|-------|-------|-------|
| Image | `registry.example.com/aoe:latest` | Your registry path |
| Ports | `8000:8000` | Frontend exposure |
| Memory | 1024MB | Minimum 512MB, 1GB recommended |
| CPU | 1.0 | Minimum 0.5 |
| Restart Policy | `unless-stopped` | Prevents accidental restarts |

### 3. Set Environment Variables

Configure the following environment variables in the ArangoCD console:

| Variable | Required | Example Value | Description |
|----------|----------|---------------|-------------|
| `ARANGO_HOST` | Yes | `https://your-deploy.arangodb.cloud` | ArangoDB server URL |
| `ARANGO_DB` | Yes | `OntoExtract` | Database name |
| `ARANGO_USER` | Yes | `root` | ArangoDB username |
| `ARANGO_PASSWORD` | Yes | `your-strong-password` | ArangoDB password |
| `ANTHROPIC_API_KEY` | Yes* | `sk-ant-...` | Anthropic API key |
| `OPENAI_API_KEY` | Yes* | `sk-proj-...` | OpenAI API key |
| `APP_SECRET_KEY` | Yes | `<openssl rand -hex 32>` | App secret key |
| `APP_ENV` | No | `production` | Environment (`production`, `development`) |
| `APP_LOG_LEVEL` | No | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LLM_EXTRACTION_MODEL` | No | `claude-sonnet-4-20250514` | LLM for extraction |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | Embedding model |
| `EXTRACTION_PASSES` | No | `3` | Number of extraction passes |
| `CORS_ORIGINS` | No | `https://aoe.your-deploy.arangodb.cloud` | Allowed CORS origins |

\* At least one of `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is required.

### 4. Launch the Container

1. Click **"Deploy"** in the ArangoCD console
2. Monitor the container logs for:
   - `"Migrations complete"` — database setup success
   - `"Backend is ready."` — FastAPI is running
   - `"Arango-OntoExtract is ready!"` — deployment complete

### 5. Access the Application

ArangoCD provides a URL for your container. Typical access:

| Service | URL | Description |
|---------|-----|-------------|
| Frontend UI | `https://aoe.your-deploy.arangodb.cloud` | Main application |
| API Docs | `https://aoe.your-deploy.arangodb.cloud/docs` | Swagger/OpenAPI docs |
| API Health | `https://aoe.your-deploy.arangodb.cloud/health` | Health check endpoint |
| Readiness | `https://aoe.your-deploy.arangodb.cloud/ready` | Kubernetes readiness |

---

## Option B: Standalone Docker

### 1. Build the Image

```bash
# From the project root
docker build -t aoe:latest .
```

### 2. Create a `.env` File

Copy the template and configure it:

```bash
cp .env.example .env
```

Edit `.env` with your values:

```bash
ARANGO_HOST=http://localhost:8529
ARANGO_DB=OntoExtract
ARANGO_USER=root
ARANGO_PASSWORD=changeme
ANTHROPIC_API_KEY=sk-ant-your-key-here
OPENAI_API_KEY=sk-proj-your-key-here
APP_SECRET_KEY=$(openssl rand -hex 32)
APP_ENV=production
```

### 3. Run the Container

```bash
docker run -d \
  --name aoe \
  -p 8000:8000 \
  --env-file .env \
  --restart unless-stopped \
  aoe:latest
```

Or use docker-compose:

```bash
docker-compose -f docker-compose.dev.yml up -d
```

### 4. Access the Application

| Service | URL | Description |
|---------|-----|-------------|
| Frontend UI | `http://localhost:8000` | Main application |
| API Docs | `http://localhost:8000/docs` | Swagger/OpenAPI docs |
| Health Check | `http://localhost:8000/health` | Health endpoint |

---

## Option C: Docker Compose (Development)

For local development with a bundled ArangoDB instance:

```bash
# Start ArangoDB + AOE
docker-compose -f docker-compose.dev.yml up -d

# View logs
docker-compose -f docker-compose.dev.yml logs -f aoe

# Stop
docker-compose -f docker-compose.dev.yml down

# Reset (includes volume cleanup)
docker-compose -f docker-compose.dev.yml down -v
```

---

## Troubleshooting

### Migration Errors

If migrations fail, check the container logs:

```bash
docker logs <container_id>
```

Common causes:
- Incorrect `ARANGO_HOST`, `ARANGO_USER`, or `ARANGO_PASSWORD`
- Database doesn't exist (create it manually first)
- Network connectivity issues between container and ArangoDB

**Fix:** Verify connection settings and ensure ArangoDB is accessible.

### Backend Health Check Fails

The entrypoint waits up to 30 seconds for the backend:

```
ERROR: Backend did not become healthy within 30s
```

Common causes:
- Missing dependencies (LLM API keys)
- Python import errors
- ArangoDB connection refused

**Fix:** Check the backend logs for specific error messages.

### Frontend Not Loading

If the frontend shows a blank page:
- Check browser console for CORS errors
- Verify `CORS_ORIGINS` includes your frontend URL
- Ensure nginx is running: `docker exec <container> nginx -t`

### Nginx Not Starting

If you see `"Nginx failed to start"`:
- Port 8000 may be in use
- Check nginx config: `docker exec <container> cat /etc/nginx/nginx.conf`
- Verify permissions: files must be owned by the `aoe` user

### Memory Issues

If the container crashes with OOM errors:
- Increase memory limit to at least 1GB
- Reduce `EXTRACTION_PASSES` if processing large documents
- Consider using external Redis for rate limiting state

```bash
docker update --memory=2g <container_id>
```

### Scaling for Production

For production deployments:

1. **Increase backend workers:**
   ```bash
   # Add to environment variables
   BACKEND_WORKERS=4
   ```

2. **Use external Redis for rate limiting:**
   ```bash
   REDIS_URL=redis://your-redis-host:6379/0
   RATE_LIMIT_ENABLED=true
   ```

3. **Disable internal rate limiter if using external LB:**
   ```bash
   RATE_LIMIT_ENABLED=false
   ```

4. **Tune extraction settings:**
   ```bash
   EXTRACTION_PASSES=5
   EXTRACTION_CONFIDENCE_MIN=0.7
   ```

5. **Use a load balancer:**
   - Deploy behind NGINX, Caddy, or cloud LB
   - Configure health checks to `http://<host>:8000/health`
   - Set idle timeout to at least 300s for long extraction tasks

---

## Image Size and Optimization

### Expected Image Size

| Component | Size |
|-----------|------|
| Python runtime + deps | ~400MB |
| Node.js + Next.js | ~200MB |
| Nginx + utilities | ~50MB |
| **Total (target)** | **~650-700MB** |

### Size Verification

```bash
docker images aoe:latest
```

Expected output:
```
REPOSITORY   TAG       SIZE
aoe          latest    680MB
```

### Optimization Tips

1. **Multi-stage builds** are already used to minimize final image size
2. **Alpine-based Node stages** reduce build-time dependencies
3. **`--no-install-recommends`** in apt skips unnecessary packages
4. **`rm -rf /var/lib/apt/lists/*`** cleans package cache

---

## Security Best Practices

1. **Never commit `.env` files** — use `.env.example` as a guide
2. **Use strong `APP_SECRET_KEY`** values in production:
   ```bash
   openssl rand -hex 32
   ```
3. **Rotate ArangoDB passwords** regularly
4. **Pin image versions** in production:
   ```bash
   docker build -t registry.example.com/aoe:1.0.0 .
   ```
5. **Enable HTTPS** via reverse proxy or ArangoCD TLS settings
6. **Review CORS origins** to only allow trusted domains

---

## Monitoring and Logs

### Container Logs

```bash
# Follow logs
docker logs -f <container_id>

# View last 100 lines
docker logs --tail 100 <container_id>

# View timestamps
docker logs --timestamps <container_id>
```

### Health Checks

```bash
# Health endpoint
curl http://localhost:8000/health

# Readiness check
curl http://localhost:8000/ready

# API docs
curl http://localhost:8000/docs
```

### Docker Stats

```bash
docker stats aoe
```

---

## Updating the Deployment

### Rebuild and Redeploy

1. **Make changes** to the codebase
2. **Rebuild the image:**
   ```bash
   docker build -t registry.example.com/aoe:latest .
   docker push registry.example.com/aoe:latest
   ```
3. **Redeploy in ArangoCD:**
   - Navigate to deployment → Containers
   - Update image tag
   - Apply changes

4. **Verify:**
   - Check logs for `"Arango-OntoExtract is ready!"`
   - Test frontend and API endpoints
   - Run a sample extraction to validate

### Rolling Back

If the new deployment has issues:

1. **In ArangoCD:**
   - Navigate to deployment → Containers
   - Change image back to previous tag
   - Apply changes

2. **In standalone Docker:**
   ```bash
   docker stop aoe
   docker rm aoe
   docker run -d --name aoe -p 8000:8000 --env-file .env aoe:previous-tag
   ```

---

## Support and Resources

- **Documentation:** `docs/` directory
- **Issue Tracker:** GitHub issues
- **API Reference:** `/docs` endpoint when running
- **Configuration:** `.env.example` for all available options