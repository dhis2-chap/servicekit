# Job Scheduler

Servicekit provides an async job scheduler for managing long-running tasks with real-time status monitoring via Server-Sent Events (SSE).

## Quick Start

### Submit a Job

```bash
# Start the example service
fastapi dev examples/job_scheduler/main.py

# Submit a 30-second computation job and capture job ID
JOB_ID=$(curl -s -X POST http://localhost:8000/api/v1/compute \
  -H "Content-Type: application/json" \
  -d '{"duration": 30}' | jq -r '.job_id')

echo "Job ID: $JOB_ID"
```

Response:
```json
{
  "job_id": "01JQRS7X...",
  "message": "Job submitted. Use polling (GET /api/v1/jobs/01JQRS7X...) or streaming (GET /api/v1/jobs/01JQRS7X.../$stream)",
  "poll_url": "/api/v1/jobs/01JQRS7X...",
  "stream_url": "/api/v1/jobs/01JQRS7X.../$stream"
}
```

### Monitor Job Status (Real-Time SSE)

```bash
# Stream status updates in real-time
curl -N http://localhost:8000/api/v1/jobs/$JOB_ID/\$stream
```

Output (streaming):
```
data: {"id":"01JQRS7X...","status":"pending","submitted_at":"2025-10-12T..."}

data: {"id":"01JQRS7X...","status":"running","started_at":"2025-10-12T..."}

data: {"id":"01JQRS7X...","status":"completed","finished_at":"2025-10-12T...","artifact_id":null}
```

**Note:** Use `-N` flag to disable cURL buffering for real-time streaming.

### Fetch the Result

The example exposes a result endpoint alongside the generic job endpoints:

```bash
curl http://localhost:8000/api/v1/compute/$JOB_ID/result
```

Response:
```json
{
  "job_id": "01JQRS7X...",
  "status": "completed",
  "submitted_at": "2025-10-12T15:30:00Z",
  "started_at": "2025-10-12T15:30:01Z",
  "finished_at": "2025-10-12T15:30:31Z",
  "result": 42,
  "error": null
}
```

---

## Job Lifecycle

Jobs progress through these states:

1. **pending** - Job submitted, waiting to start
2. **running** - Job is currently executing
3. **completed** - Job finished successfully
4. **failed** - Job encountered an error
5. **canceled** - Job was canceled by user

### Terminal States

These states indicate the job is finished:
- `completed` - Success
- `failed` - Error occurred
- `canceled` - User canceled

SSE streams automatically close when a terminal state is reached.

---

## Polling vs Streaming

### Traditional Polling

```bash
# Client must repeatedly poll every second
while true; do
  curl http://localhost:8000/api/v1/jobs/01JQRS7X...
  sleep 1
done
```

**Problems:**
- Wastes bandwidth (repeated full HTTP requests)
- Polling interval trade-off (fast = expensive, slow = delayed updates)
- Client-side polling logic needed

### SSE Streaming

```bash
# Server pushes updates automatically
curl -N http://localhost:8000/api/v1/jobs/01JQRS7X.../\$stream
```

**Benefits:**
- Efficient (single HTTP connection, server pushes updates)
- Real-time (updates sent immediately when status changes)
- Standard (W3C EventSource API built into browsers)
- Simple (no client-side polling logic)

---

## Real-Time Streaming with SSE

Server-Sent Events (SSE) provide efficient real-time updates over a single HTTP connection.

### Browser JavaScript (EventSource API)

```javascript
const jobId = "01JQRS7X...";
const eventSource = new EventSource(`/api/v1/jobs/${jobId}/$stream`);

eventSource.onmessage = (event) => {
  const job = JSON.parse(event.data);
  console.log(`Status: ${job.status}`);

  // Update UI
  document.getElementById('status').textContent = job.status;

  // Close connection when done
  if (['completed', 'failed', 'canceled'].includes(job.status)) {
    console.log('Job finished');
    eventSource.close();
  }
};

eventSource.onerror = (error) => {
  console.error('SSE connection error:', error);
  eventSource.close();
};
```

### cURL (Command Line)

```bash
# Stream job status updates
curl -N http://localhost:8000/api/v1/jobs/01JQRS7X.../\$stream

# Custom poll interval (default: 0.5 seconds)
curl -N "http://localhost:8000/api/v1/jobs/01JQRS7X.../\$stream?poll_interval=1.0"
```

**Important:** Use `-N` / `--no-buffer` flag to disable buffering and see real-time updates.

### Python (httpx)

```python
import httpx
import json

job_id = "01JQRS7X..."
url = f"http://localhost:8000/api/v1/jobs/{job_id}/$stream"

with httpx.stream("GET", url) as response:
    for line in response.iter_lines():
        if line.startswith("data: "):
            data = line[6:]  # Remove "data: " prefix
            job = json.loads(data)
            print(f"Status: {job['status']}")

            # Stop when terminal state reached
            if job['status'] in ['completed', 'failed', 'canceled']:
                break
```

### Python (requests - Not Recommended)

The `requests` library buffers responses by default, making it unsuitable for SSE. Use `httpx` instead.

---

## Configuration

### BaseServiceBuilder Setup

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_jobs(max_concurrency=5)  # Limit concurrent jobs
    .build()
)
```

**Parameters:**
- `max_concurrency` (`int | None`): Maximum concurrent jobs. `None` = unlimited.

### SSE Poll Interval

The SSE endpoint polls the scheduler internally at configurable intervals:

```bash
# Default: 0.5 seconds
curl -N http://localhost:8000/api/v1/jobs/01JQRS.../\$stream

# Custom: 1.0 second
curl -N "http://localhost:8000/api/v1/jobs/01JQRS.../\$stream?poll_interval=1.0"
```

**Recommendations:**
- **Development**: 0.5s (default) - good balance
- **Production**: 1.0s - reduces server load
- **High-frequency**: 0.1s - near real-time (use sparingly)

---

## API Reference

### POST /api/v1/jobs

**Not exposed directly.** Submit jobs via custom endpoints (e.g., `/api/v1/compute`).

### GET /api/v1/jobs

List all jobs with optional status filtering.

```bash
# List all jobs
curl http://localhost:8000/api/v1/jobs

# Filter by status
curl http://localhost:8000/api/v1/jobs?status_filter=completed
```

### GET /api/v1/jobs/{job_id}

Get job status and details (single request).

```bash
curl http://localhost:8000/api/v1/jobs/01JQRS7X...
```

Response:
```json
{
  "id": "01JQRS7X...",
  "status": "running",
  "submitted_at": "2025-10-12T15:30:00Z",
  "started_at": "2025-10-12T15:30:01Z",
  "finished_at": null,
  "error": null,
  "artifact_id": null
}
```

### GET /api/v1/jobs/{job_id}/$stream

Stream real-time job status updates via Server-Sent Events.

**Query Parameters:**
- `poll_interval` (float, default: 0.5): Seconds between status checks

**Response Format:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

data: {"id":"...","status":"pending",...}

data: {"id":"...","status":"running",...}

data: {"id":"...","status":"completed",...}
```

**Connection closes automatically** when job reaches terminal state.

### DELETE /api/v1/jobs/{job_id}

Cancel and delete a job.

```bash
curl -X DELETE http://localhost:8000/api/v1/jobs/01JQRS7X...
```

Returns `204 No Content` on success.

---

## Error Handling

### Invalid Job ID (400)

```json
{
  "detail": "Invalid job ID format"
}
```

### Job Not Found (404)

```json
{
  "detail": "Job not found"
}
```

### Failed Jobs

When a job fails, the `error` field contains the error message:

```json
{
  "id": "01JQRS7X...",
  "status": "failed",
  "error": "ValueError: Invalid input",
  "error_traceback": "Traceback (most recent call last):\n..."
}
```

### Job Deletion During Streaming

If a job is deleted while being streamed, the SSE connection sends a final event and closes:

```
data: {"status": "deleted"}
```

---

## Testing

### Manual Testing

**Terminal 1: Start service**
```bash
fastapi dev examples/job_scheduler/main.py
```

**Terminal 2: Submit job and stream status**
```bash
# Submit job and capture job ID
JOB_ID=$(curl -s -X POST http://localhost:8000/api/v1/compute \
  -H "Content-Type: application/json" \
  -d '{"duration": 30}' | jq -r '.job_id')

echo "Job ID: $JOB_ID"

# Stream status updates in real-time
curl -N http://localhost:8000/api/v1/jobs/$JOB_ID/\$stream
```

### Browser Testing

1. Submit job via Swagger UI: http://localhost:8000/docs
2. Open browser console (F12)
3. Run JavaScript:

```javascript
const jobId = "01JQRS7X...";  // From Swagger response
const es = new EventSource(`/api/v1/jobs/${jobId}/$stream`);
es.onmessage = (e) => console.log(JSON.parse(e.data));
```

---

## Production Deployment

### Concurrency Limits

Set `max_concurrency` to prevent resource exhaustion:

```python
.with_jobs(max_concurrency=10)  # Max 10 concurrent jobs
```

**Recommendations:**
- **CPU-bound jobs**: Set to number of CPU cores
- **I/O-bound jobs**: Higher limits OK (10-50)
- **Memory-intensive**: Lower limits to prevent OOM

### Load Balancers and Proxies

SSE requires special configuration for long-lived connections.

**nginx:**
```nginx
location /api/v1/jobs {
    proxy_pass http://backend;
    proxy_buffering off;  # Required for SSE
    proxy_read_timeout 600s;  # Allow long connections
    proxy_http_version 1.1;
}
```

**Apache:**
```apache
<Location /api/v1/jobs>
    ProxyPass http://backend
    ProxyPassReverse http://backend
    ProxyPreserveHost On
    SetEnv proxy-nokeepalive 1
</Location>
```

**AWS ALB:**
- Enable HTTP/2 (supports SSE)
- Set idle timeout ≥ 60 seconds

### Monitoring

Track job metrics:

```python
# Example: Prometheus metrics
from prometheus_client import Counter, Histogram

job_submissions = Counter('jobs_submitted_total', 'Total jobs submitted')
job_duration = Histogram('job_duration_seconds', 'Job execution time')
```

---

## Troubleshooting

### Stream Closes Immediately

**Problem:** SSE connection closes right after opening.

**Causes:**
1. Job already in terminal state
2. Invalid job ID

**Solution:**
```bash
# Check job status first
curl http://localhost:8000/api/v1/jobs/01JQRS7X...

# If completed/failed/canceled, stream will close immediately
```

### No Updates Appearing

**Problem:** Connected but no events streaming.

**Causes:**
1. cURL buffering enabled
2. Proxy buffering responses

**Solution:**
```bash
# Use -N flag with cURL
curl -N http://localhost:8000/api/v1/jobs/01JQRS7X.../\$stream

# Check proxy configuration (see Production Deployment)
```

### EventSource Not Working in Browser

**Problem:** JavaScript EventSource API fails or doesn't connect.

**Causes:**
1. CORS issues
2. HTTPS mixed content (HTTPS page, HTTP EventSource)
3. Ad blockers

**Solution:**
```javascript
// Check for errors
const es = new EventSource('/api/v1/jobs/01JQRS.../$stream');
es.onerror = (e) => {
  console.error('EventSource error:', e);
  console.log('ReadyState:', es.readyState);  // 0=connecting, 1=open, 2=closed
};

// CORS: Ensure same origin or proper CORS headers
// HTTPS: Use HTTPS for both page and EventSource
// Ad blockers: Disable and test
```

### High CPU Usage

**Problem:** Scheduler consuming excessive CPU.

**Causes:**
1. Too many concurrent jobs
2. Short poll_interval with many streams

**Solution:**
```python
# Limit concurrent jobs
.with_jobs(max_concurrency=10)
```

```bash
# Increase poll interval
curl -N "http://localhost:8000/api/v1/jobs/01JQRS.../\$stream?poll_interval=1.0"
```

---

## Examples

### Complete Workflow

```bash
# 1. Submit job and extract job_id
JOB_ID=$(curl -s -X POST http://localhost:8000/api/v1/compute \
  -H "Content-Type: application/json" \
  -d '{"duration": 30}' | jq -r '.job_id')

echo "Job ID: $JOB_ID"

# 2. Stream status updates in real-time
curl -N http://localhost:8000/api/v1/jobs/$JOB_ID/\$stream
```

### React Component

```jsx
import { useEffect, useState } from 'react';

function JobStatus({ jobId }) {
  const [job, setJob] = useState(null);

  useEffect(() => {
    const eventSource = new EventSource(`/api/v1/jobs/${jobId}/$stream`);

    eventSource.onmessage = (event) => {
      const jobData = JSON.parse(event.data);
      setJob(jobData);

      // Close when finished
      if (['completed', 'failed', 'canceled'].includes(jobData.status)) {
        eventSource.close();
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return () => eventSource.close();
  }, [jobId]);

  return (
    <div>
      <h3>Job {jobId}</h3>
      <p>Status: {job?.status || 'connecting...'}</p>
      {job?.error && <p className="error">{job.error}</p>}
    </div>
  );
}
```

### Vue Component

```vue
<template>
  <div>
    <h3>Job {{ jobId }}</h3>
    <p>Status: {{ job?.status || 'connecting...' }}</p>
    <p v-if="job?.error" class="error">{{ job.error }}</p>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';

const props = defineProps(['jobId']);
const job = ref(null);
let eventSource;

onMounted(() => {
  eventSource = new EventSource(`/api/v1/jobs/${props.jobId}/$stream`);

  eventSource.onmessage = (event) => {
    const jobData = JSON.parse(event.data);
    job.value = jobData;

    if (['completed', 'failed', 'canceled'].includes(jobData.status)) {
      eventSource.close();
    }
  };
});

onUnmounted(() => {
  eventSource?.close();
});
</script>
```

---

## Next Steps

- **Artifact Storage**: Jobs can return ULIDs to link results

For more examples:
- `examples/job_scheduler/main.py` - Job scheduler with SSE streaming
