# Monitoring Demo

Demonstrates Servicekit's built-in monitoring capabilities with OpenTelemetry and Prometheus metrics.

## Features

- **Prometheus Metrics**: Exposed at `/metrics` endpoint
- **OpenTelemetry Instrumentation**: Automatic tracing for FastAPI and SQLAlchemy
- **Request Metrics**: HTTP request duration, counts by status code
- **Database Metrics**: SQLAlchemy connection pool statistics
- **Process Metrics**: CPU, memory, and Python runtime metrics
- **Health Checks**: Built-in health endpoint at `/health`
- **Structured Logging**: JSON-formatted logs with request context

## Quick Start

### Local Development

```bash
# Install dependencies
uv sync

# Run the service
uv run uvicorn main:app --reload
```

The API will be available at http://localhost:8000

### Docker Deployment

```bash
# Build and run with Docker Compose
docker compose up

# Run in detached mode
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

## Endpoints

- `GET /health` - Health check (returns healthy/unhealthy status)
- `GET /api/v1/system` - Service information and metadata
- `GET /metrics` - Prometheus metrics (text format)
- `GET /docs` - Swagger UI API documentation
- `GET /redoc` - ReDoc API documentation

## Viewing Metrics

### Direct Access

Visit http://localhost:8000/metrics to see raw Prometheus metrics:

```
# HELP http_server_request_duration_seconds Duration of HTTP server requests.
# TYPE http_server_request_duration_seconds histogram
http_server_request_duration_seconds_bucket{http_request_method="GET",http_response_status_code="200",http_route="/health",le="0.005",...} 42.0
http_server_request_duration_seconds_bucket{http_request_method="GET",http_response_status_code="200",http_route="/health",le="0.01",...} 42.0
...
http_server_request_duration_seconds_count{http_request_method="GET",http_response_status_code="200",http_route="/health",...} 42.0

# HELP sqlalchemy_pool_size Connection pool size
# TYPE sqlalchemy_pool_size gauge
sqlalchemy_pool_size{pool="default"} 5.0
```

### With Prometheus

1. **Install Prometheus** (macOS):
```bash
brew install prometheus
```

2. **Configure Prometheus** (`prometheus.yml`):
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'servicekit'
    static_configs:
      - targets: ['localhost:8000']
```

3. **Run Prometheus**:
```bash
prometheus --config.file=prometheus.yml
```

4. **Access Prometheus UI**: http://localhost:9090

5. **Query metrics**:
   - `rate(http_server_request_duration_seconds_count[5m])` - Request rate
   - `http_server_request_duration_seconds_count` - Total requests
   - `sqlalchemy_pool_size` - Database connection pool

### With Grafana

See `examples/docker/compose.monitoring.yml` for a full monitoring stack with Grafana dashboards.

## Available Metrics

### HTTP Metrics

Recorded by FastAPI OpenTelemetry:

- `http_server_request_duration_seconds` (histogram) - Request latency; `_count` gives total requests
  - Labels: `http_request_method`, `http_response_status_code`, `http_route`
- `http_server_active_requests` (gauge) - In-flight requests
  - Labels: `http_request_method`

### Database Metrics

- `sqlalchemy_pool_size` (gauge) - Connection pool size
- `sqlalchemy_pool_checked_in` (gauge) - Available connections
- `sqlalchemy_pool_checked_out` (gauge) - In-use connections
- `sqlalchemy_pool_overflow` (gauge) - Overflow connections

### Process Metrics

- `process_cpu_seconds_total` (counter) - CPU time
- `process_resident_memory_bytes` (gauge) - Memory usage
- `python_info` (gauge) - Python version info
- `python_gc_objects_collected_total` (counter) - GC collections

## Example Queries

### Average Request Duration (5m)
```promql
rate(http_server_request_duration_seconds_sum[5m]) / rate(http_server_request_duration_seconds_count[5m])
```

### Request Rate by Status Code
```promql
sum by (http_response_status_code) (rate(http_server_request_duration_seconds_count[5m]))
```

### 95th Percentile Request Duration
```promql
histogram_quantile(0.95, rate(http_server_request_duration_seconds_bucket[5m]))
```

### Database Connection Pool Usage
```promql
sqlalchemy_pool_checked_out / sqlalchemy_pool_size
```

## Testing the Metrics

Generate some load to see metrics in action:

```bash
# Health check requests
for i in {1..100}; do curl -s http://localhost:8000/health > /dev/null; done

# System info requests
for i in {1..50}; do curl -s http://localhost:8000/api/v1/system > /dev/null; done

# View updated metrics
curl http://localhost:8000/metrics | grep http_server_request_duration_seconds_count
```

## OpenTelemetry Integration

The service automatically instruments:

- **FastAPI**: All HTTP routes, using FastAPI OpenTelemetry
- **SQLAlchemy**: Database queries and connection pool

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to also export traces, metrics and logs over OTLP.

Traces include:
- Request method, path, status code
- SQL queries and execution time
- Database connection acquisition
- Dependency resolution, endpoint and serialization spans

## Structured Logging

Logs are emitted in JSON format with request context:

```json
{
  "event": "HTTP request",
  "method": "GET",
  "path": "/health",
  "status": 200,
  "duration": 0.003,
  "timestamp": "2025-10-20T12:00:00Z"
}
```

## Production Deployment

### Environment Variables

```bash
# Logging
LOG_FORMAT=json
LOG_LEVEL=INFO

# Server
PORT=8000
WORKERS=4
```

### Prometheus Scraping

Add to Prometheus configuration:

```yaml
scrape_configs:
  - job_name: 'servicekit-prod'
    static_configs:
      - targets: ['prod-server:8000']
    scrape_interval: 30s
    metrics_path: '/metrics'
```

### Grafana Dashboards

Import pre-built dashboards for:
- HTTP request rates and latencies
- Error rates by endpoint
- Database connection pool usage
- System resource utilization

See `examples/docker/monitoring/grafana/dashboards/` for examples.

## Alerting Examples

### High Error Rate

```yaml
alert: HighErrorRate
expr: rate(http_server_request_duration_seconds_count{http_response_status_code=~"5.."}[5m]) > 0.05
for: 5m
labels:
  severity: warning
annotations:
  summary: "High 5xx error rate detected"
```

### Database Connection Pool Exhaustion

```yaml
alert: DatabasePoolExhausted
expr: sqlalchemy_pool_checked_out / sqlalchemy_pool_size > 0.9
for: 2m
labels:
  severity: critical
annotations:
  summary: "Database connection pool nearly exhausted"
```

## Troubleshooting

### Metrics Not Appearing

1. Ensure the builder does not call `.with_monitoring(enabled=False)`
2. Check logs for `monitoring.enabled`
3. Verify `/metrics` endpoint returns data
4. Check Prometheus scrape targets status

### High Memory Usage

1. Review `process_resident_memory_bytes` metric
2. Check for connection pool leaks
3. Monitor Python GC metrics
4. Consider reducing worker count

### Slow Requests

1. Use `http_server_request_duration_seconds` histogram
2. Identify slow endpoints with `rate()` queries
3. Check database query performance
4. Review SQLAlchemy connection pool metrics

## Next Steps

- Deploy full monitoring stack with Grafana
- Configure alerting rules in Prometheus
- Create custom dashboards for your metrics
- Add application-specific metrics
- Integrate with distributed tracing (Jaeger, Zipkin)

## Related Examples

- `core_api/` - Basic CRUD API service
- `auth/` - API key authentication
- `job_scheduler/` - Background job execution

## Postman Collection

A Postman collection is included for easy API testing. Import the collection file into Postman:

**Import Steps:**
1. Open Postman
2. Click **Import** button
3. Select the `.postman_collection.json` file from this directory
4. Click **Import**

**Collection Features:**
- Pre-configured requests for all endpoints
- Auto-captured variables (IDs from responses)
- Test scripts for validation
- Example workflows

**Variables:**
- `baseUrl`: Default `http://127.0.0.1:8000`
- `user_id`: Auto-set from create requests
- `api_key`: Set your API key (for auth demos)

See the collection file for complete request examples and workflows.
