# Service Registration

Servicekit provides automatic service registration with an orchestrator for service discovery in Docker Compose and Kubernetes environments.

## Quick Start

### Basic Registration

The simplest approach with auto-detected hostname:

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_registration()  # Reads SERVICEKIT_ORCHESTRATOR_URL from environment
    .build()
)
```

Set the environment variable:

```bash
export SERVICEKIT_ORCHESTRATOR_URL=http://orchestrator:9000/services/$register
fastapi run your_file.py
```

### Docker Compose

The recommended approach for multi-service deployments:

```yaml
services:
  orchestrator:
    image: your-orchestrator:latest
    ports:
      - "9000:9000"

  my-service:
    image: your-service:latest
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/services/$register
      # Hostname auto-detected from container name
    depends_on:
      - orchestrator
```

### Custom ServiceInfo

For services with additional metadata:

```python
from servicekit.api import ServiceInfo

class CustomServiceInfo(ServiceInfo):
    """Extended service info with custom fields."""
    deployment_env: str = "production"
    team: str = "platform"
    capabilities: list[str] = []

app = (
    BaseServiceBuilder(
        info=CustomServiceInfo(
            id="my-service",
            display_name="My Service",
            version="1.0.0",
            deployment_env="staging",
            team="data-science",
            capabilities=["ml-inference", "analytics"],
        )
    )
    .with_registration()
    .build()
)
```

---

## Configuration Options

The `.with_registration()` method accepts these parameters:

```python
.with_registration(
    orchestrator_url=None,              # Direct value or env var
    host=None,                          # Direct value, auto-detect, or env var
    port=None,                          # Direct value, env var, or 8000
    orchestrator_url_env="SERVICEKIT_ORCHESTRATOR_URL",
    host_env="SERVICEKIT_HOST",
    port_env="SERVICEKIT_PORT",
    max_retries=5,                      # Number of registration attempts
    retry_delay=2.0,                    # Seconds between retries
    fail_on_error=False,                # Abort startup on failure
    timeout=10.0,                       # HTTP request timeout
    enable_keepalive=True,              # Enable periodic ping to keep service alive
    keepalive_interval=10.0,            # Seconds between keepalive pings
    auto_deregister=True,               # Automatically deregister on shutdown
    service_key=None,                   # Service key for authentication
    service_key_env="SERVICEKIT_REGISTRATION_KEY",  # Env var for service key
)
```

### ServiceInfo ID Field

The `id` field is **required** on `ServiceInfo` and must follow slug format:

- Lowercase letters, numbers, and hyphens only
- Must start with a letter
- No consecutive hyphens
- No trailing or leading hyphens

**Valid examples:** `my-service`, `chap-ewars`, `prediction-service`, `service1`

**Invalid examples:** `My-Service` (uppercase), `my_service` (underscore), `1-service` (starts with number)

```python
# Valid
ServiceInfo(id="my-service", display_name="My Service")

# Invalid - will raise ValidationError
ServiceInfo(id="My-Service", display_name="My Service")  # uppercase
ServiceInfo(id="my_service", display_name="My Service")  # underscore
```

### Parameters

- **orchestrator_url** (`str | None`): Orchestrator registration endpoint URL. If None, reads from environment variable.
- **host** (`str | None`): Service hostname. If None, auto-detects via `socket.gethostname()` or reads from environment variable.
- **port** (`int | None`): Service port. If None, reads from environment variable or defaults to 8000.
- **orchestrator_url_env** (`str`): Environment variable name for orchestrator URL. Default: `SERVICEKIT_ORCHESTRATOR_URL`.
- **host_env** (`str`): Environment variable name for hostname override. Default: `SERVICEKIT_HOST`.
- **port_env** (`str`): Environment variable name for port override. Default: `SERVICEKIT_PORT`.
- **max_retries** (`int`): Maximum number of registration attempts. Default: 5.
- **retry_delay** (`float`): Delay in seconds between retry attempts. Default: 2.0.
- **fail_on_error** (`bool`): If True, raise exception and abort startup on registration failure. If False, log warning and continue. Default: False.
- **timeout** (`float`): HTTP request timeout in seconds. Default: 10.0.
- **enable_keepalive** (`bool`): Enable periodic pings to keep service registered. Default: True.
- **keepalive_interval** (`float`): Seconds between keepalive pings. Default: 10.0.
- **auto_deregister** (`bool`): Automatically deregister service on shutdown. Default: True.
- **service_key** (`str | None`): Service key for authentication. If provided, sent as `X-Service-Key` header. Default: None.
- **service_key_env** (`str`): Environment variable name for service key. Default: `SERVICEKIT_REGISTRATION_KEY`.

---

## How It Works

### Registration Flow

1. **Service Starts**: FastAPI application initializes during lifespan startup
2. **Hostname Resolution**: Determines service hostname (see resolution order below)
3. **Port Resolution**: Determines service port (see resolution order below)
4. **URL Construction**: Builds service URL as `http://<hostname>:<port>`
5. **Payload Creation**: Serializes ServiceInfo to JSON (supports custom subclasses)
6. **Registration Request**: Sends POST to orchestrator endpoint
7. **Retry on Failure**: Retries with delay if request fails
8. **Keepalive Started**: If enabled, background task starts pinging orchestrator
9. **Service Runs**: Service handles requests while staying alive via pings
10. **Shutdown**: On graceful shutdown, stops keepalive and optionally deregisters
11. **Logging**: Logs all registration, ping, and deregistration events

**Readiness gate**: before registering, the service polls its own health endpoint and waits for a 200 response.
Because `/health` now returns 503 while any health check is unhealthy, a service whose database (or other check)
is down waits instead of registering as available. See the [health checks guide](health-checks.md) for the status
code semantics.

### Keepalive and TTL

Services can be configured to send periodic "ping" requests to the orchestrator to indicate they're still alive. The orchestrator tracks a Time-To-Live (TTL) for each service and automatically removes services that haven't pinged within the TTL window.

**How it works:**

1. **Initial Registration**: Service registers and receives response with:
   - `id`: Unique ULID identifier for this service
   - `ttl_seconds`: How long until service expires (default: 30 seconds)
   - `ping_url`: Endpoint to send keepalive pings (automatically provided by orchestrator)

2. **Keepalive Loop**: Background task automatically sends PUT requests to `ping_url` every N seconds:
   - Default interval: 10 seconds (configurable via `keepalive_interval`)
   - Each ping resets the service's expiration time
   - Failures are logged but don't crash the service

3. **TTL Expiration**: Orchestrator runs cleanup every 5 seconds:
   - Removes services that haven't pinged within TTL window
   - Logs expired services for monitoring

4. **Graceful Shutdown**: On service shutdown:
   - Keepalive task stops (no more pings)
   - Service explicitly deregisters (if `auto_deregister=True`)
   - Immediate removal from registry

**Configuration examples:**

```python
# Default: keepalive enabled, auto-deregister on shutdown
.with_registration()

# Disable keepalive (rely on manual health checks)
.with_registration(enable_keepalive=False)

# Custom keepalive interval (faster pings)
.with_registration(keepalive_interval=5.0)

# Don't deregister on shutdown (let TTL expire naturally)
.with_registration(auto_deregister=False)
```

### Registration Payload

The service sends this payload to the orchestrator:

```json
{
  "id": "my-service",
  "url": "http://my-service:8000",
  "info": {
    "id": "my-service",
    "display_name": "My Service",
    "version": "1.0.0",
    ...
  }
}
```

For custom ServiceInfo subclasses:

```json
{
  "id": "ml-service",
  "url": "http://ml-service:8000",
  "info": {
    "id": "ml-service",
    "display_name": "ML Service",
    "version": "2.0.0",
    "deployment_env": "production",
    "team": "data-science",
    "capabilities": ["ml-inference", "feature-extraction"],
    "priority": 5
  }
}
```

### Registration Response

The orchestrator responds with registration details, including the ping endpoint:

```json
{
  "id": "my-service",
  "status": "registered",
  "service_url": "http://my-service:8000",
  "message": "Service registered successfully",
  "ttl_seconds": 30,
  "ping_url": "http://orchestrator:9000/services/my-service/$ping"
}
```

**Key fields:**
- `id`: Service identifier (matches the `id` field from ServiceInfo)
- `ttl_seconds`: Time-to-live in seconds (service must ping within this window)
- `ping_url`: Endpoint for keepalive pings (automatically used by the service)

**Important**: The service ID is defined by the service itself via `ServiceInfo.id`, not assigned by the orchestrator. This makes registration idempotent - re-registering the same service updates the existing entry rather than creating a new one.

### Hostname Resolution

Priority order:

1. **Direct Parameter**: `host="my-service"` in `.with_registration()`
2. **Auto-Detection**: `socket.gethostname()` (returns Docker container name or hostname)
3. **Environment Variable**: Value of `SERVICEKIT_HOST` (or custom env var)
4. **Error**: Raises exception if `fail_on_error=True`, otherwise logs warning

**Docker Behavior**: In Docker Compose, `socket.gethostname()` returns the service name or container ID, making auto-detection work seamlessly.

### Port Resolution

Priority order:

1. **Direct Parameter**: `port=8080` in `.with_registration()`
2. **Environment Variable**: Value of `SERVICEKIT_PORT` (or custom env var)
3. **Default**: 8000

**Important**: `SERVICEKIT_PORT` should match the container's **internal port**, not the host-mapped port.

---

## Examples

### Environment Variables (Production)

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(info=ServiceInfo(id="production-service", display_name="Production Service"))
    .with_logging()
    .with_health()
    .with_registration()  # Reads from environment
    .build()
)
```

**docker-compose.yml:**
```yaml
services:
  my-service:
    image: my-service:latest
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/services/$register
      # SERVICEKIT_HOST auto-detected
      # SERVICEKIT_PORT defaults to 8000
```

### Direct Configuration (Testing)

```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="test-service", display_name="Test Service"))
    .with_registration(
        orchestrator_url="http://localhost:9000/services/$register",
        host="test-service",
        port=8080,
    )
    .build()
)
```

### Custom Environment Variable Names

```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_registration(
        orchestrator_url_env="MY_APP_ORCHESTRATOR_URL",
        host_env="MY_APP_HOST",
        port_env="MY_APP_PORT",
    )
    .build()
)
```

**Environment:**
```bash
export MY_APP_ORCHESTRATOR_URL=http://orchestrator:9000/services/$register
export MY_APP_HOST=my-service
export MY_APP_PORT=8000
```

### Fail-Fast Mode

For critical services that must register:

```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="critical-service", display_name="Critical Service"))
    .with_registration(
        fail_on_error=True,  # Abort startup if registration fails
        max_retries=10,
        retry_delay=1.0,
    )
    .build()
)
```

### Custom Retry Strategy

```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_registration(
        max_retries=10,      # More attempts
        retry_delay=1.0,     # Faster retries
        timeout=5.0,         # Shorter timeout
    )
    .build()
)
```

---

## Docker Compose

### Basic Setup

```yaml
services:
  orchestrator:
    image: orchestrator:latest
    ports:
      - "9000:9000"

  service-a:
    image: my-service:latest
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/services/$register
    depends_on:
      - orchestrator
```

### With Health Checks

Wait for orchestrator to be healthy before starting services:

```yaml
services:
  orchestrator:
    image: orchestrator:latest
    ports:
      - "9000:9000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/health"]
      interval: 10s
      timeout: 5s
      retries: 3

  service-a:
    image: my-service:latest
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/services/$register
    depends_on:
      orchestrator:
        condition: service_healthy  # Wait for healthy status
```

### Custom Port Mapping

When container port differs from host port:

```yaml
services:
  service-a:
    image: my-service:latest
    ports:
      - "8001:8000"  # Host:Container
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/services/$register
      SERVICEKIT_PORT: "8000"  # Use container port, not host port
```

**Why**: Other services connect using the internal Docker network, so they use the container port (8000), not the host-mapped port (8001).

### Multiple Services

```yaml
services:
  orchestrator:
    image: orchestrator:latest
    ports:
      - "9000:9000"

  service-a:
    image: my-service:latest
    ports:
      - "8000:8000"
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/services/$register

  service-b:
    image: my-service:latest
    ports:
      - "8001:8000"
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/services/$register
```

Both services register with different hostnames (service-a, service-b) but same internal port (8000).

---

## Kubernetes

### ConfigMap for Orchestrator URL

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: registration-config
data:
  orchestrator-url: "http://orchestrator-service:9000/services/$register"
```

### Deployment with Registration

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-service
spec:
  replicas: 3
  template:
    metadata:
      labels:
        app: my-service
    spec:
      containers:
        - name: my-service
          image: my-service:latest
          env:
            - name: SERVICEKIT_ORCHESTRATOR_URL
              valueFrom:
                configMapKeyRef:
                  name: registration-config
                  key: orchestrator-url
            - name: SERVICEKIT_HOST
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name  # Pod name
```

### Service Discovery

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  selector:
    app: my-service
  ports:
    - port: 8000
      targetPort: 8000
```

---

## Error Handling

### Retry Behavior

By default, registration retries 5 times with 2-second delays:

```python
.with_registration(
    max_retries=5,      # Total attempts
    retry_delay=2.0,    # Seconds between attempts
)
```

Example timeline:
- Attempt 1: Immediate
- Attempt 2: After 2 seconds
- Attempt 3: After 4 seconds (2s + 2s)
- Attempt 4: After 6 seconds
- Attempt 5: After 8 seconds

### Fail on Error

**Default (fail_on_error=False)**: Service starts even if registration fails

```python
.with_registration(fail_on_error=False)  # Log warning, continue
```

**Fail-Fast (fail_on_error=True)**: Service aborts startup if registration fails

```python
.with_registration(fail_on_error=True)  # Raise exception, abort
```

**When to use fail-fast**:
- Critical services that require orchestrator awareness
- Production environments with strict registration requirements
- Services that cannot function without being registered

### Structured Logging

All registration events are logged with structured data:

```json
{
  "event": "registration.starting",
  "orchestrator_url": "http://orchestrator:9000/services/$register",
  "service_url": "http://my-service:8000",
  "host_source": "auto-detected",
  "port_source": "default",
  "max_retries": 5
}
```

Success:
```json
{
  "event": "registration.success",
  "service_url": "http://my-service:8000",
  "attempt": 1,
  "status_code": 200
}
```

Failure:
```json
{
  "event": "registration.attempt_failed",
  "service_url": "http://my-service:8000",
  "attempt": 1,
  "max_retries": 5,
  "error": "Connection refused",
  "error_type": "ConnectError"
}
```

---

## Troubleshooting

### Registration Fails

**Check orchestrator is reachable:**

```bash
# From service container
docker compose exec my-service curl http://orchestrator:9000/health
```

**Check environment variables:**

```bash
docker compose exec my-service env | grep SERVICEKIT
```

**View registration logs:**

```bash
docker compose logs my-service | grep registration
```

### Hostname Auto-Detection Issues

**Problem**: Auto-detection fails or returns unexpected value

**Solution**: Override with environment variable

```yaml
environment:
  SERVICEKIT_HOST: my-custom-hostname
```

**Debug hostname detection:**

```bash
docker compose exec my-service hostname
docker compose exec my-service python -c "import socket; print(socket.gethostname())"
```

### Port Mismatch

**Problem**: Orchestrator cannot reach service at registered URL

**Common mistake**: Using host-mapped port instead of container port

```yaml
# WRONG
ports:
  - "8001:8000"
environment:
  SERVICEKIT_PORT: "8001"  # ❌ Host port

# CORRECT
ports:
  - "8001:8000"
environment:
  SERVICEKIT_PORT: "8000"  # ✅ Container port
```

**Why**: Services communicate via Docker's internal network using container ports, not host-mapped ports.

### Orchestrator URL Missing

**Problem**: No orchestrator URL configured

**Error**: `registration.missing_orchestrator_url`

**Solution**: Set environment variable

```bash
export SERVICEKIT_ORCHESTRATOR_URL=http://orchestrator:9000/services/$register
```

Or use direct configuration:

```python
.with_registration(orchestrator_url="http://orchestrator:9000/services/$register")
```

### Service Not Appearing in Registry

**Check orchestrator logs:**

```bash
docker compose logs orchestrator
```

**Check service startup logs:**

```bash
docker compose logs my-service | grep registration
```

**Verify orchestrator endpoint:**

```bash
curl http://localhost:9000/services
```

---

## Production Considerations

### High Availability

Use multiple orchestrator replicas:

```yaml
services:
  orchestrator:
    image: orchestrator:latest
    deploy:
      replicas: 3

  service-a:
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/services/$register
```

### Retry Strategy

Adjust retries for production reliability:

```python
.with_registration(
    max_retries=10,       # More attempts
    retry_delay=1.0,      # Faster retries
    timeout=30.0,         # Longer timeout
    fail_on_error=True,   # Fail fast in production
)
```

### Security

**Service Key Authentication**: Configure a service key to authenticate with the orchestrator. The key is sent as an `X-Service-Key` header with all registration requests (register, keepalive, deregister).

```python
# Using environment variable (recommended)
.with_registration()  # Reads from SERVICEKIT_REGISTRATION_KEY

# Using direct parameter (testing)
.with_registration(service_key="my-secret-key")

# Using custom environment variable
.with_registration(service_key_env="MY_APP_REGISTRATION_KEY")
```

**Docker Compose with service key:**

```yaml
services:
  my-service:
    image: my-service:latest
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/services/$register
      SERVICEKIT_REGISTRATION_KEY: ${REGISTRATION_SECRET}
```

**TLS**: Use HTTPS for orchestrator communication

```python
.with_registration(
    orchestrator_url="https://orchestrator:9443/services/$register"
)
```

### Monitoring

Monitor registration health:
- Track registration success/failure rates
- Alert on repeated registration failures
- Monitor orchestrator availability
- Log all registration attempts for audit

---

## Related Examples

- `examples/registration/` - Complete registration demo with orchestrator
- `core_api/` - Basic CRUD service
- `monitoring/` - Prometheus metrics
- `auth/` - Environment-based authentication

## See Also

- [Health Checks](health-checks.md) - Configure health endpoints
- [Monitoring](monitoring.md) - Prometheus metrics
- [Authentication](authentication.md) - API key authentication
