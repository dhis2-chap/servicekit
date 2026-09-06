# Authentication

Servicekit provides simple API key authentication for service-to-service communication in Docker Compose and Kubernetes environments.

## Quick Start

### Environment Variables (Recommended for Production)

The simplest and most secure approach for production deployments:

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_auth()  # Reads from SERVICEKIT_API_KEYS environment variable
    .with_database("sqlite+aiosqlite:///./data.db")
    .build()
)
```

Set the environment variable:

```bash
export SERVICEKIT_API_KEYS="sk_prod_abc123,sk_prod_xyz789"
fastapi run your_file.py
```

### Docker Secrets (Most Secure for Production)

For Docker Swarm or Kubernetes deployments:

```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_auth(api_key_file="/run/secrets/api_keys")
    .build()
)
```

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  app:
    image: your-app
    secrets:
      - api_keys

secrets:
  api_keys:
    file: ./secrets/api_keys.txt
```

**secrets/api_keys.txt:**
```
sk_prod_abc123
sk_prod_xyz789
```

### Direct Keys (Development Only)

**WARNING:** Never use this in production!

```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_auth(api_keys=["sk_dev_test123"])  # NOT for production
    .build()
)
```

---

## Configuration Options

The `.with_auth()` method accepts these parameters:

```python
.with_auth(
    api_keys=None,                      # Direct list (dev only)
    api_key_file=None,                  # File path (Docker secrets)
    env_var="SERVICEKIT_API_KEYS",         # Environment variable name
    header_name="X-API-Key",            # HTTP header for API key
    unauthenticated_paths=None,         # Paths without auth
)
```

### Priority

Servicekit uses the first non-None value in this order:
1. `api_keys` (direct list)
2. `api_key_file` (file path)
3. `env_var` (environment variable, default: `SERVICEKIT_API_KEYS`)

### Parameters

- **api_keys** (`List[str] | None`): Direct list of API keys. Only for examples and local development.
- **api_key_file** (`str | None`): Path to file containing keys (one per line). For Docker secrets.
- **env_var** (`str`): Environment variable name to read keys from. Default: `SERVICEKIT_API_KEYS`.
- **header_name** (`str`): HTTP header name for API key. Default: `X-API-Key`.
- **unauthenticated_paths** (`List[str] | None`): Exact paths that don't require authentication. Omit the parameter
  (or pass `None`) to use the defaults: `/`, `/docs`, `/redoc`, `/openapi.json`, `/health`. Pass an explicit list to
  replace the defaults, or an empty list (`[]`) to require authentication on every path.

---

## Key Format Conventions

**Recommended format:** `sk_{environment}_{random}`

### Examples

```
sk_prod_a1b2c3d4e5f6g7h8     # Production
sk_staging_x1y2z3a4b5c6d7e8  # Staging
sk_dev_test123               # Development
```

### Why This Format?

- **sk_** prefix: Easily identifiable as a secret key
- **environment**: Know which environment the key belongs to
- **random**: Unique identifier (16+ characters recommended)

Servicekit logs only the first 7 characters (`sk_prod_****`) for security.

---

## Key Rotation

To rotate API keys without downtime:

1. **Add new key** (keep old key active)
2. **Update clients** to use new key
3. **Remove old key** after all clients updated

### Example Rotation

```bash
# Step 1: Both keys active
export SERVICEKIT_API_KEYS="sk_prod_old123,sk_prod_new456"

# Deploy and verify service restarts
fastapi run your_file.py

# Step 2: Update all clients to use sk_prod_new456
# Test that clients work with new key

# Step 3: Remove old key (after confirming all clients updated)
export SERVICEKIT_API_KEYS="sk_prod_new456"

# Restart service
fastapi run your_file.py
```

---

## Unauthenticated Paths

By default, these paths don't require authentication:

- `/docs` - Swagger UI
- `/redoc` - ReDoc
- `/openapi.json` - OpenAPI schema
- `/health` - Health check
- `/` - Landing page

### Custom Unauthenticated Paths

```python
.with_auth(
    unauthenticated_paths=["/health", "/public", "/status"]
)
```

This **replaces** the default list. To add to the default list:

```python
default_paths = ["/docs", "/redoc", "/openapi.json", "/health", "/"]
custom_paths = default_paths + ["/public", "/status"]

.with_auth(unauthenticated_paths=custom_paths)
```

---

## Testing Authenticated APIs

### With cURL

```bash
# Valid request
curl -H "X-API-Key: sk_dev_test123" http://localhost:8000/api/v1/configs

# Missing key (returns 401)
curl http://localhost:8000/api/v1/configs

# Invalid key (returns 401)
curl -H "X-API-Key: invalid_key" http://localhost:8000/api/v1/configs

# Unauthenticated path (no key needed)
curl http://localhost:8000/health
```

### With Python requests

```python
import requests

headers = {"X-API-Key": "sk_dev_test123"}

# Authenticated request
response = requests.get(
    "http://localhost:8000/api/v1/configs",
    headers=headers
)

# Check response
assert response.status_code == 200
```

### With httpx (async)

```python
import httpx

headers = {"X-API-Key": "sk_dev_test123"}

async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://localhost:8000/api/v1/configs",
        headers=headers
    )
    assert response.status_code == 200
```

---

## Docker Deployment

### Docker Compose

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  servicekit-service:
    image: your-servicekit-app
    ports:
      - "8000:8000"
    environment:
      # Option 1: Environment variable
      SERVICEKIT_API_KEYS: sk_prod_abc123,sk_prod_xyz789

      # Option 2: Point to secrets file
      # SERVICEKIT_API_KEY_FILE: /run/secrets/api_keys

    # Option 2 (continued): Mount secrets
    # secrets:
    #   - api_keys

# secrets:
#   api_keys:
#     file: ./secrets/api_keys.txt
```

**secrets/api_keys.txt:**
```
# Production API keys
# One key per line, comments allowed
sk_prod_abc123
sk_prod_xyz789
```

**.gitignore:**
```
# Never commit secrets!
secrets/api_keys.txt
```

**secrets/api_keys.txt.example:**
```
# Example API keys file
# Copy to api_keys.txt and replace with real keys
sk_prod_example1
sk_prod_example2
```

### Docker Swarm

```bash
# Create secret
echo -e "sk_prod_abc123\nsk_prod_xyz789" | \
  docker secret create servicekit_api_keys -

# Deploy service
docker service create \
  --name my-servicekit-service \
  --secret servicekit_api_keys \
  -e SERVICEKIT_API_KEY_FILE=/run/secrets/servicekit_api_keys \
  -p 8000:8000 \
  your-servicekit-app
```

---

## Kubernetes Deployment

**secret.yaml:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: servicekit-api-keys
type: Opaque
stringData:
  api_keys.txt: |
    sk_prod_abc123
    sk_prod_xyz789
```

**deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: servicekit-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: servicekit-service
  template:
    metadata:
      labels:
        app: servicekit-service
    spec:
      containers:
      - name: app
        image: your-servicekit-app
        ports:
        - containerPort: 8000
        env:
        - name: SERVICEKIT_API_KEY_FILE
          value: /etc/secrets/api_keys.txt
        volumeMounts:
        - name: api-keys
          mountPath: /etc/secrets
          readOnly: true
      volumes:
      - name: api-keys
        secret:
          secretName: servicekit-api-keys
```

---

## Logging

Servicekit automatically logs authentication events with **masked keys** for security.

### Successful Authentication

```json
{
  "event": "auth.success",
  "key_prefix": "sk_prod",
  "path": "/api/v1/configs"
}
```

### Failed Authentication

```json
{
  "event": "auth.invalid_key",
  "key_prefix": "sk_unkn",
  "path": "/api/v1/configs",
  "method": "GET"
}
```

### Missing Key

```json
{
  "event": "auth.missing_key",
  "path": "/api/v1/configs",
  "method": "GET"
}
```

Only the **first 7 characters** of keys are logged. Full keys are never logged.

---

## Security Best Practices

### Recommended Practices

- Use environment variables or Docker secrets in production
- Use `sk_env_random` format for easy identification in logs
- Rotate keys regularly (quarterly recommended)
- Use different keys for different services/environments
- Keep `.env` files in `.gitignore`
- Use minimum 16 characters for key randomness
- Monitor authentication logs for failed attempts

### Avoid

- Committing API keys to git (use `.gitignore`)
- Using `api_keys=` parameter in production (only for examples)
- Reusing keys across environments (dev/staging/prod)
- Using weak/short keys (minimum 16 characters)
- Sharing keys via email/Slack (use secrets management)
- Hardcoding keys in source code

---

## Error Responses

All authentication errors follow RFC 9457 Problem Details format.

### Missing API Key (401)

```json
{
  "type": "urn:servicekit:error:unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "Missing authentication header: X-API-Key",
  "instance": "/api/v1/configs"
}
```

### Invalid API Key (401)

```json
{
  "type": "urn:servicekit:error:unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "Invalid API key",
  "instance": "/api/v1/configs"
}
```

---

## Advanced Usage

### Custom Header Name

```python
.with_auth(
    header_name="X-Custom-API-Key"
)
```

Test with:
```bash
curl -H "X-Custom-API-Key: sk_dev_test123" http://localhost:8000/api/v1/configs
```

### Multiple Environments

**Development:**
```python
# dev.py
.with_auth(api_keys=["sk_dev_test123"])
```

**Production:**
```python
# prod.py
.with_auth()  # Reads from SERVICEKIT_API_KEYS env var
```

### Service-to-Service Communication

```python
# Service A (client)
import httpx

headers = {"X-API-Key": os.getenv("SERVICE_B_API_KEY")}
async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://service-b:8000/api/v1/data",
        headers=headers
    )

# Service B (server)
app = BaseServiceBuilder(info=info).with_auth().build()
```

---

## Troubleshooting

### "No API keys configured" Error

**Problem:** Service fails to start with error message.

**Solution:** Ensure you've provided keys via one of these methods:
```bash
# Environment variable
export SERVICEKIT_API_KEYS="sk_dev_test123"

# Or in Python (dev only)
.with_auth(api_keys=["sk_dev_test123"])

# Or via file
.with_auth(api_key_file="/path/to/keys.txt")
```

### 401 Unauthorized on Health Check

**Problem:** Health check returns 401 instead of 200.

**Solution:** Health checks are unauthenticated by default. If you customized `unauthenticated_paths`, add `/health` back:

```python
.with_auth(
    unauthenticated_paths=[
        "/docs", "/redoc", "/openapi.json",
        "/health",  # Add this
        "/", "/custom/path"
    ]
)
```

### Keys Not Loading from File

**Problem:** `FileNotFoundError: API key file not found`

**Solution:**
1. Verify file path is absolute: `/run/secrets/api_keys` (not relative)
2. Check file exists: `ls -la /run/secrets/api_keys`
3. Verify container has access (Docker secrets mount at `/run/secrets/`)

### Keys Not Loading from Environment

**Problem:** "No API keys found in SERVICEKIT_API_KEYS"

**Solution:**
1. Verify env var is set: `echo $SERVICEKIT_API_KEYS`
2. Check for typos in variable name
3. Ensure keys are comma-separated: `key1,key2,key3`
4. No spaces around commas: `sk_dev_1,sk_dev_2` (not `sk_dev_1, sk_dev_2`)

---

## Next Steps

- **Rate Limiting:** See roadmap for per-key rate limiting (P2)
- **Key Scoping:** See roadmap for endpoint-specific keys (P2)
- **Monitoring:** Track authentication metrics with Prometheus (P1)

For more examples, see:
- `examples/auth/main.py` - Basic authentication example
- `CLAUDE.md` - Comprehensive development guide
