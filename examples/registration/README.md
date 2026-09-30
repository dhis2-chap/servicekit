# Service Registration Demo

Demonstrates automatic service registration with an orchestrator for service discovery in Docker Compose environments.

## Features

- **Automatic Registration**: Services register themselves on startup
- **Hostname Auto-Detection**: Uses Docker container hostname automatically
- **Retry Logic**: Configurable retries with delays
- **Custom Metadata**: Support for ServiceInfo subclasses with additional fields
- **Mock Orchestrator**: Simple orchestrator for testing and development
- **Multi-Service Setup**: Example with multiple services (svca, svcb)
- **Keepalive & TTL**: Services send periodic pings to stay registered (30s TTL, 10s interval)
- **Auto-Deregistration**: Services gracefully deregister on shutdown
- **Valkey-based Storage**: TTL and expiration handled by Valkey (no manual cleanup needed)

## Quick Start

### Local Development

**Prerequisites**: Valkey or Redis running on localhost:6379

#### Run Orchestrator

```bash
# Start Valkey (using Docker)
docker run -d -p 6379:6379 valkey/valkey:8

# Install dependencies
cd examples/registration
uv sync

# Run the mock orchestrator
uv run python orchestrator.py
```

The orchestrator will be available at http://localhost:9000

#### Run Service

In a separate terminal:

```bash
# Set orchestrator URL
export SERVICEKIT_ORCHESTRATOR_URL=http://localhost:9000/services/\$register

# Run the service
uv run uvicorn main:app --reload
```

The service will automatically register with the orchestrator on startup.

### Docker Deployment

```bash
# Build and run all services (orchestrator + svca + svcb)
docker compose up --build

# Run in detached mode
docker compose up -d

# View logs
docker compose logs -f

# View orchestrator logs only
docker compose logs -f orchestrator

# Stop
docker compose down
```

## Architecture

```
┌─────────────┐     ┌────────┐
│ Orchestrator│────→│ Valkey │  TTL-based service expiration
│   (port 9000)│     │  :6379 │
└──────▲──────┘     └────────┘
       │
       │ HTTP POST on startup
       │
   ┌───┴────────────┐
   │                │
┌──┴───┐      ┌────┴──┐
│ svca │      │ svcb  │
│ :8000│      │ :8001 │
└──────┘      └───────┘
```

## Endpoints

### Service Endpoints (svca, svcb)

- `GET /health` - Health check
- `GET /api/v1/system` - Service information
- `GET /api/v1/info` - ServiceInfo metadata
- `GET /` - Landing page
- `GET /docs` - Swagger UI

### Orchestrator Endpoints

- `POST /services/$register` - Register a service (returns service_id, ttl_seconds, ping_url)
- `PUT /services/{id}/$ping` - Send keepalive ping to extend TTL
- `GET /services` - List all registered services
- `GET /services/{id}` - Get specific service details by ULID
- `DELETE /services/{id}` - Deregister a service by ULID
- `GET /health` - Orchestrator health check

## Registration Flow

1. **Service Starts**: Container starts and FastAPI app initializes
2. **Hostname Detection**: Auto-detects hostname via `socket.gethostname()` (returns Docker container name/ID)
3. **Port Resolution**: Advertises `SERVICEKIT_PORT` or defaults to 8000 (the local bind port is probed separately for readiness)
4. **URL Construction**: Builds service URL: `http://<hostname>:<port>`
5. **Registration Attempt**: Sends POST to orchestrator with payload:
   ```json
   {
     "id": "registration-example",
     "url": "http://svca:8000",
     "info": {
       "id": "registration-example",
       "display_name": "Registration Example Service",
       "version": "1.0.0",
       ...
     }
   }
   ```
6. **Registration Confirmed**: Orchestrator returns:
   ```json
   {
     "id": "registration-example",
     "status": "registered",
     "service_url": "http://svca:8000",
     "message": "...",
     "ttl_seconds": 30,
     "ping_url": "http://orchestrator:9000/services/registration-example/$ping"
   }
   ```
7. **Keepalive Started**: Background task starts sending pings every 10 seconds to `ping_url`
8. **Service Runs**: Service handles requests while keepalive maintains registration
9. **Retry on Failure**: Initial registration retries up to 5 times with 2-second delay
10. **Graceful Shutdown**: On shutdown, service stops keepalive and deregisters explicitly
11. **Success/Failure Logging**: Logs all registration, ping, and deregistration events

## Keepalive and TTL

### How It Works

The orchestrator uses Valkey's built-in TTL mechanism for automatic service expiration:

- **TTL**: 30 seconds (configurable in `orchestrator.py`)
- **Ping Interval**: 10 seconds (services send keepalive every 10s)
- **Expiration**: Handled automatically by Valkey (no manual cleanup task needed)

**Timeline Example:**
- `T+0s`: Service registers, Valkey stores with `EX 30` (expires at T+30s)
- `T+10s`: Service pings, Valkey resets TTL to 30s (expires at T+40s)
- `T+20s`: Service pings, Valkey resets TTL to 30s (expires at T+50s)
- `T+30s`: Service pings, Valkey resets TTL to 30s (expires at T+60s)
- If service crashes at `T+35s` and stops pinging:
  - `T+65s`: Valkey automatically removes the key (30s after last ping)
  - Service no longer appears in registry

### Ping Endpoint

**Request:**
```bash
PUT /services/{service_id}/$ping
```

**Response:**
```json
{
  "id": "01K83B5V85PQZ1HTH4DQ7NC9JM",
  "status": "alive",
  "last_ping_at": "2025-10-27T12:00:30.000Z",
  "expires_at": "2025-10-27T12:01:00.000Z"
}
```

### Configuration Options

Services can configure keepalive behavior:

```python
# Default: keepalive enabled, 10s interval, auto-deregister on shutdown
.with_registration()

# Disable keepalive (service expires after 30s if not manually pinged)
.with_registration(enable_keepalive=False)

# Custom ping interval (faster keepalive)
.with_registration(keepalive_interval=5.0)

# Don't deregister on shutdown (let TTL expire naturally)
.with_registration(auto_deregister=False)
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICEKIT_ORCHESTRATOR_URL` | (required) | Orchestrator registration endpoint |
| `SERVICEKIT_HOST` | auto-detected | Service hostname (override auto-detection) |
| `SERVICEKIT_PORT` | 8000 | Port advertised to the orchestrator |
| `PORT` | (unset) | Port the app binds locally, probed for readiness (exported by `run_app`) |
| `SERVICEKIT_REGISTRATION_KEY` | (optional) | Service key for authenticated registration |

### Builder Configuration

```python
.with_registration(
    orchestrator_url=None,              # Override env var
    host=None,                          # Override auto-detection
    port=None,                          # Override default
    orchestrator_url_env="SERVICEKIT_ORCHESTRATOR_URL",
    host_env="SERVICEKIT_HOST",
    port_env="SERVICEKIT_PORT",
    max_retries=5,
    retry_delay=2.0,
    fail_on_error=False,               # Don't abort on failure
    timeout=10.0,
    service_key=None,                   # Service key for authentication
    service_key_env="SERVICEKIT_REGISTRATION_KEY",
    local_port=None,                    # Local bind port for the readiness probe
    local_port_env="PORT",
)
```

### Service Key Authentication

When registering with an orchestrator that requires authentication, you can configure a service key that will be sent as an `X-Service-Key` header with all registration requests (register, keepalive pings, deregister).

**Using environment variable (recommended for production):**

```yaml
services:
  my-service:
    image: my-service:latest
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/services/$register
      SERVICEKIT_REGISTRATION_KEY: ${REGISTRATION_SECRET}
```

**Using direct parameter (for testing):**

```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_registration(
        orchestrator_url="http://orchestrator:9000/services/$register",
        service_key="my-secret-key",
    )
    .build()
)
```

**Using custom environment variable name:**

```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_registration(
        service_key_env="MY_APP_REGISTRATION_KEY",
    )
    .build()
)
```

The service key is included in:
- Initial registration (`POST /services/$register`)
- Keepalive pings (`PUT /services/{id}/$ping`)
- Deregistration (`DELETE /services/{id}`)

## Examples

### Basic Registration (main.py)

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_logging()
    .with_health()
    .with_registration()  # Auto-detect hostname
    .build()
)
```

### Custom ServiceInfo (main_custom.py)

```python
class CustomServiceInfo(ServiceInfo):
    deployment_env: str = "production"
    team: str = "platform"
    capabilities: list[str] = []
    priority: int = 1

app = (
    BaseServiceBuilder(
        info=CustomServiceInfo(
            id="custom-service",
            display_name="Custom Service",
            deployment_env="staging",
            team="data-science",
            capabilities=["ml-inference"],
            priority=5,
        )
    )
    .with_registration()
    .build()
)
```

### Custom Environment Variables

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

### Direct Configuration (Testing)

```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_registration(
        orchestrator_url="http://orchestrator:9000/register",
        host="my-service",
        port=8080,
        max_retries=10,
        retry_delay=1.0,
        fail_on_error=True,  # Abort startup on failure
    )
    .build()
)
```

## Testing the Registration

### 1. Start All Services

```bash
docker compose up -d
```

### 2. Check Service Logs

```bash
# Check svca registration
docker compose logs svca | grep registration

# Expected output:
# registration.starting orchestrator_url=http://orchestrator:9000/register ...
# registration.success service_url=http://svca:8000 ...
```

### 3. Query Orchestrator

```bash
# List all registered services
curl http://localhost:9000/services | jq

# Get specific service by ULID
curl http://localhost:9000/services/01K83B5V85PQZ1HTH4DQ7NC9JM | jq

# Expected output:
{
  "id": "01K83B5V85PQZ1HTH4DQ7NC9JM",
  "url": "http://svca:8000",
  "info": {
    "display_name": "Registration Example Service",
    "version": "1.0.0",
    ...
  },
  "registered_at": "2025-10-21T12:00:00.000Z",
  "last_updated": "2025-10-21T12:00:00.000Z"
}
```

### 4. Check Service Health

```bash
# Via orchestrator's perspective
curl http://svca:8000/health

# From host (Docker port mapping)
curl http://localhost:8000/health
curl http://localhost:8001/health  # svcb
```

## Hostname Resolution

### Auto-Detection (Recommended for Docker)

In Docker Compose, `socket.gethostname()` returns the container hostname (service name or container ID):

```yaml
services:
  my-service:  # hostname = "my-service"
    image: my-image
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/register
      # SERVICEKIT_HOST auto-detected as "my-service"
```

### Manual Override

For non-Docker or custom hostname scenarios:

```yaml
services:
  my-service:
    image: my-image
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/register
      SERVICEKIT_HOST: custom-hostname
```

### Resolution Priority

1. Direct `host` parameter in `.with_registration(host="...")`
2. `socket.gethostname()` (Docker container name)
3. Environment variable `SERVICEKIT_HOST`
4. Error if none available

## Port Configuration

### Default Behavior

Services default to port 8000:

```yaml
services:
  my-service:
    image: my-image
    ports:
      - "8000:8000"  # Maps container port 8000 to host port 8000
```

### Custom Port

```yaml
services:
  my-service:
    image: my-image
    ports:
      - "8001:8000"  # Host sees 8001, container uses 8000
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: http://orchestrator:9000/register
      # SERVICEKIT_PORT defaults to 8000 (correct for intra-container communication)
```

**Important**: `SERVICEKIT_PORT` is the port the **orchestrator** uses to reach the service. Here the orchestrator shares the Docker network, so that is the container port (8000). An orchestrator on the Docker host would instead need the host-mapped port (8001) with `SERVICEKIT_HOST=host.docker.internal`.

### Resolution Priority

Advertised port:

1. Direct `port` parameter in `.with_registration(port=...)`
2. Environment variable `SERVICEKIT_PORT`
3. Default to 8000

Local port probed for readiness: `local_port` if set, otherwise `PORT`, the advertised port, and 8000 are tried in turn.

## Error Handling

### Retry Logic

By default, registration retries 5 times with 2-second delays:

```python
.with_registration(
    max_retries=5,      # Total attempts
    retry_delay=2.0,    # Seconds between attempts
)
```

### Fail on Error

By default, services continue even if registration fails:

```python
.with_registration(
    fail_on_error=False  # Log warning and continue
)
```

For critical services that require registration:

```python
.with_registration(
    fail_on_error=True  # Raise exception and abort startup
)
```

### Structured Logging

All registration events are logged:

```json
{
  "event": "registration.starting",
  "orchestrator_url": "http://orchestrator:9000/register",
  "service_url": "http://svca:8000",
  "host_source": "auto-detected",
  "port_source": "default",
  "max_retries": 5
}

{
  "event": "registration.success",
  "service_url": "http://svca:8000",
  "attempt": 1,
  "status_code": 200
}
```

## Production Deployment

### Docker Compose with Secrets

```yaml
services:
  my-service:
    image: my-service:latest
    environment:
      SERVICEKIT_ORCHESTRATOR_URL: ${ORCHESTRATOR_URL}  # e.g., http://orchestrator:9000/services/$register
    env_file:
      - .env.production
```

### Kubernetes

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
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-service
spec:
  template:
    spec:
      containers:
        - name: my-service
          image: my-service:latest
          env:
            - name: SERVICEKIT_ORCHESTRATOR_URL
              value: "http://orchestrator-service:9000/services/$register"
            - name: SERVICEKIT_HOST
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name  # Pod name
```

## Troubleshooting

### Registration Fails

Check orchestrator is reachable:

```bash
docker compose exec svca curl http://orchestrator:9000/health
```

Check environment variables:

```bash
docker compose exec svca env | grep SERVICEKIT
```

### Hostname Detection Issues

Override hostname explicitly:

```yaml
environment:
  SERVICEKIT_HOST: my-custom-hostname
```

### Service Not Appearing in Registry

Check orchestrator logs:

```bash
docker compose logs orchestrator
```

Check service logs for registration attempts:

```bash
docker compose logs svca | grep registration
```

### Port Mismatch

Ensure `SERVICEKIT_PORT` is the port as seen from the orchestrator (the container port on a shared Docker network):

```yaml
ports:
  - "8001:8000"  # Host:Container
environment:
  SERVICEKIT_PORT: "8000"  # Orchestrator on the same Docker network
```

## Related Examples

- `core_api/` - Basic CRUD service
- `monitoring/` - Prometheus metrics
- `auth/` - Environment-based authentication
- `job_scheduler/` - Background job execution

## Next Steps

- Implement your own orchestrator with persistent storage
- Add service health monitoring from orchestrator
- Integrate with service mesh (Istio, Linkerd)
- Add authentication between services and orchestrator
- Implement service deregistration on graceful shutdown
- Add service metadata versioning and updates
