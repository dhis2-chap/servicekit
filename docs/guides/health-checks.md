# Health Checks and Monitoring

Servicekit provides comprehensive health check capabilities for service monitoring, including one-time health checks and continuous streaming for real-time monitoring.

## Quick Start

Enable health checks in your service:

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_health()  # Enables /health endpoint
    .build()
)
```

Your service now exposes health endpoints at `/health` and `/health/$stream`.

## Endpoints

### One-Time Health Check

**Endpoint**: `GET /health`

Returns current health status in a single response:

```bash
curl http://localhost:8000/health
```

**Response**:
```json
{
  "status": "healthy"
}
```

**Use Cases**:
- Kubernetes liveness/readiness probes
- Load balancer health checks
- Manual health verification
- CI/CD deployment validation

### Continuous Health Monitoring (SSE)

**Endpoint**: `GET /health/$stream`

Streams health status updates continuously using Server-Sent Events (SSE):

```bash
# Stream with default 1.0s interval
curl -N http://localhost:8000/health/\$stream

# Stream with custom 2.0s interval
curl -N "http://localhost:8000/health/\$stream?poll_interval=2.0"
```

**Response Format** (text/event-stream):
```
data: {"status":"healthy"}

data: {"status":"healthy"}

data: {"status":"healthy"}
```

**Query Parameters**:
- `poll_interval` (float): Seconds between health checks. Default: 1.0

**Use Cases**:
- Real-time dashboard monitoring
- Continuous integration tests
- Service health visualization
- Alert detection systems
- Development/debugging

**Note**: Stream continues indefinitely until client disconnects. Use Ctrl+C to stop.

## Custom Health Checks

Add custom health checks to monitor specific subsystems:

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo
from servicekit.api.routers.health import HealthState

async def check_database() -> tuple[HealthState, str | None]:
    """Check database connectivity."""
    try:
        # Test database connection
        async with get_session() as session:
            await session.execute("SELECT 1")
        return (HealthState.HEALTHY, None)
    except Exception as e:
        return (HealthState.UNHEALTHY, f"Database error: {str(e)}")

async def check_redis() -> tuple[HealthState, str | None]:
    """Check Redis connectivity."""
    try:
        # Test Redis connection
        await redis_client.ping()
        return (HealthState.HEALTHY, None)
    except Exception as e:
        return (HealthState.DEGRADED, f"Redis unavailable: {str(e)}")

app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_health(checks={
        "database": check_database,
        "redis": check_redis,
    })
    .build()
)
```

**Response with Custom Checks**:
```json
{
  "status": "degraded",
  "checks": {
    "database": {
      "state": "healthy"
    },
    "redis": {
      "state": "degraded",
      "message": "Redis unavailable: Connection refused"
    }
  }
}
```

### Health States

- **`healthy`**: All checks passed, service fully operational
- **`degraded`**: Some non-critical checks failed, service partially operational
- **`unhealthy`**: Critical checks failed, service not operational

**Aggregation Logic**:
- Overall status = worst state among all checks
- `unhealthy` > `degraded` > `healthy`
- Exception in check = `unhealthy` with error message

### HTTP Status Codes

- **200 OK**: overall status is `healthy` or `degraded` (the service can still serve traffic)
- **503 Service Unavailable**: overall status is `unhealthy`

The response body is identical in both cases, so probes and dashboards can use either the status code or the
`status` field. The SSE stream endpoint (`/health/$stream`) always responds with 200; the state is carried inside
each event.

## Kubernetes Integration

### Liveness and Readiness Probes

Use health checks for Kubernetes pod lifecycle management:

**deployment.yaml**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: servicekit-service
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: app
        image: your-servicekit-app
        ports:
        - containerPort: 8000

        # Liveness probe - restart if unhealthy
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3

        # Readiness probe - remove from service if not ready
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 2
```

**Best Practices**:
- **Liveness**: Checks if app is stuck/deadlocked (longer intervals, higher threshold)
- **Readiness**: Checks if app can serve traffic (shorter intervals, lower threshold)
- Use `/health` for both probes (not `/health/$stream`)
- Set appropriate timeouts (3-5 seconds recommended)

### Liveness Versus Readiness

Since `/health` returns 503 when any check is unhealthy, using it as a liveness probe restarts the pod whenever a
dependency (a database, an upstream API) is down, even though the process itself is fine. Prefer a dependency-free
liveness endpoint and keep `/health` for readiness.

`BaseServiceBuilder` keeps a single health configuration, so mount the second router directly on the built app:

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo
from servicekit.api.routers import HealthRouter

app = BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service")).with_health().build()

# Liveness: no checks, always 200 while the process can answer
app.include_router(HealthRouter.create(prefix="/live", tags=["Observability"]))
```

Then point `livenessProbe` at `/live` and `readinessProbe` at `/health`.

### Service Mesh Integration

For service meshes like Istio or Linkerd, health checks are used for traffic routing:

```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: servicekit-service
spec:
  host: servicekit-service
  trafficPolicy:
    outlierDetection:
      consecutiveErrors: 5
      interval: 30s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
      minHealthPercent: 40
    connectionPool:
      http:
        http1MaxPendingRequests: 100
        http2MaxRequests: 100
```

## Python Client Examples

### One-Time Health Check

```python
import httpx

async def check_service_health(base_url: str) -> bool:
    """Check if service is healthy."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{base_url}/health")
        data = response.json()
        return data["status"] == "healthy"
```

### Continuous Monitoring with SSE

```python
import httpx
import json

async def monitor_service_health(base_url: str, poll_interval: float = 1.0):
    """Monitor service health via SSE stream."""
    url = f"{base_url}/health/$stream?poll_interval={poll_interval}"

    async with httpx.AsyncClient() as client:
        async with client.stream("GET", url) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    status = data["status"]
                    print(f"Health: {status}")

                    if status != "healthy":
                        # Alert or take action
                        await send_alert(f"Service unhealthy: {data}")
```

### Health Check with Timeout

```python
import httpx
import asyncio

async def health_check_with_timeout(base_url: str, timeout: float = 3.0) -> str:
    """Check health with timeout."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base_url}/health")
            response.raise_for_status()
            data = response.json()
            return data["status"]
    except httpx.TimeoutException:
        return "timeout"
    except Exception as e:
        return f"error: {str(e)}"
```

## Load Balancer Integration

### HAProxy Configuration

```haproxy
backend servicekit_servers
    balance roundrobin
    option httpchk GET /health
    # /health returns 503 when the service is unhealthy, 200 when healthy or degraded
    http-check expect status 200

    server app1 10.0.1.10:8000 check inter 5s rise 2 fall 3
    server app2 10.0.1.11:8000 check inter 5s rise 2 fall 3
    server app3 10.0.1.12:8000 check inter 5s rise 2 fall 3
```

### NGINX Configuration

```nginx
upstream servicekit_backend {
    server 10.0.1.10:8000 max_fails=3 fail_timeout=30s;
    server 10.0.1.11:8000 max_fails=3 fail_timeout=30s;
    server 10.0.1.12:8000 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;

    location /health {
        proxy_pass http://servicekit_backend;
        proxy_connect_timeout 2s;
        proxy_read_timeout 5s;
    }

    location / {
        proxy_pass http://servicekit_backend;
        # Health check performed separately
    }
}
```

## Monitoring Dashboards

### Grafana Dashboard with SSE

Create a custom panel using SSE streaming:

```javascript
// Grafana panel plugin for SSE health monitoring
const eventSource = new EventSource('http://localhost:8000/health/$stream');

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  updateHealthStatus(data.status);

  if (data.checks) {
    updateChecksTable(data.checks);
  }
};
```

### Simple HTML Dashboard

```html
<!DOCTYPE html>
<html>
<head>
    <title>Service Health Monitor</title>
</head>
<body>
    <h1>Service Health</h1>
    <div id="status">Connecting...</div>
    <pre id="checks"></pre>

    <script>
        const eventSource = new EventSource('http://localhost:8000/health/$stream?poll_interval=2.0');

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            const statusEl = document.getElementById('status');
            const checksEl = document.getElementById('checks');

            // Update status with color coding
            statusEl.textContent = `Status: ${data.status}`;
            statusEl.style.color = data.status === 'healthy' ? 'green' :
                                   data.status === 'degraded' ? 'orange' : 'red';

            // Show detailed checks
            if (data.checks) {
                checksEl.textContent = JSON.stringify(data.checks, null, 2);
            }
        };

        eventSource.onerror = () => {
            document.getElementById('status').textContent = 'Connection lost';
            document.getElementById('status').style.color = 'red';
        };
    </script>
</body>
</html>
```

## Best Practices

### Recommended Practices

- **Enable in all services**: Health checks are essential for production reliability
- **Use custom checks**: Monitor critical dependencies (database, cache, external APIs)
- **Keep checks fast**: Health checks should complete in <1 second
- **Avoid expensive operations**: Don't run migrations, heavy queries, or external calls
- **Use appropriate states**: `degraded` for non-critical, `unhealthy` for critical failures
- **SSE for dashboards**: Use `/health/$stream` for real-time monitoring UIs
- **One-time for probes**: Use `/health` for Kubernetes and load balancers
- **Unauthenticated**: Keep health endpoints public for infrastructure access

### Avoid

- **Expensive checks**: Heavy database queries, full table scans, complex computations
- **External dependencies in liveness**: Don't make liveness depend on external services
- **High frequency polling**: Don't poll `/health` more than once per second
- **Authenticated health**: Health endpoints should be unauthenticated for infrastructure
- **Incomplete aggregation**: Always include all critical subsystems in checks

## Combining with Other Features

### With Authentication

Health endpoints should remain unauthenticated:

```python
app = (
    BaseServiceBuilder(info=info)
    .with_health()
    .with_auth(
        unauthenticated_paths=[
            "/health",        # Health check
            "/health/$stream" # Health monitoring
        ]
    )
    .build()
)
```

### With Monitoring

Combine health checks with Prometheus metrics:

```python
app = (
    BaseServiceBuilder(info=info)
    .with_health(checks={"database": check_database})
    .with_monitoring()  # Prometheus metrics at /metrics
    .build()
)
```

**Operational Endpoints**:
- `/health` - Kubernetes liveness/readiness (one-time)
- `/health/$stream` - Real-time monitoring (continuous)
- `/metrics` - Prometheus metrics (scraping)

All operational endpoints use root-level paths for easy discovery.

## Troubleshooting

### Health Check Times Out

**Problem**: Health check takes too long or times out.

**Solution**:
1. Review custom health check functions
2. Ensure checks complete in <1 second
3. Remove expensive operations (heavy queries, external calls)
4. Use connection pooling for database checks

### Health Returns Unhealthy

**Problem**: Service reports unhealthy but seems functional.

**Solution**:
1. Check logs for health check errors
2. Review custom check implementations
3. Test dependencies manually (database, cache, APIs)
4. Verify network connectivity to dependencies

### SSE Stream Disconnects

**Problem**: `/health/$stream` disconnects frequently.

**Solution**:
1. Check nginx/proxy timeout settings
2. Increase client timeout
3. Verify network stability
4. Check for reverse proxy buffering (should be disabled)

### Kubernetes Pod Restarts

**Problem**: Pods restart frequently due to liveness probe failures.

**Solution**:
1. Increase `initialDelaySeconds` for slower startup
2. Increase `failureThreshold` to allow temporary failures
3. Increase `timeoutSeconds` for slower responses
4. Review health check performance

## Examples

- `examples/monitoring/main.py` - Service with health checks and monitoring
- `examples/monitoring/postman_collection.json` - Postman collection with health endpoints

## Next Steps

- **Metrics**: Add Prometheus monitoring with `.with_monitoring()`
- **Alerting**: Set up alerts based on health status
- **Dashboards**: Create real-time monitoring dashboards with SSE
- **Custom Checks**: Implement checks for your specific dependencies

For related features, see:
- [Monitoring Guide](monitoring.md) - Prometheus metrics and OpenTelemetry
- [Job Scheduler Guide](job-scheduler.md) - Background job health monitoring
