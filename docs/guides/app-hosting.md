# App Hosting

Servicekit enables hosting static web applications (HTML/JS/CSS) alongside your FastAPI service, allowing you to serve dashboards, admin panels, documentation sites, and other web UIs from the same server as your API.

## Quick Start

### Mount a Single App

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_health()
    .with_app("./apps/dashboard")  # Mount app from filesystem
    .build()
)
```

Your dashboard is now available at the prefix defined in `manifest.json` (e.g., `/dashboard`).

### Auto-Discover Multiple Apps

```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_health()
    .with_apps("./apps")  # Discovers all subdirectories with manifest.json
    .build()
)
```

All apps in the `apps/` directory are automatically discovered and mounted.

---

## App Structure

Each app is a directory containing a `manifest.json` file and static files (HTML, CSS, JavaScript, images).

### Directory Layout

```
my-app/
├── manifest.json    # Required: App metadata and configuration
├── index.html       # Required: Entry point (configurable)
├── style.css        # Optional: Stylesheets
├── script.js        # Optional: JavaScript
└── assets/          # Optional: Images, fonts, etc.
    └── logo.png
```

### Manifest Format

**manifest.json:**
```json
{
  "name": "My Dashboard",
  "version": "1.0.0",
  "prefix": "/dashboard",
  "description": "Interactive data dashboard",
  "author": "Your Name",
  "entry": "index.html"
}
```

**Required fields:**
- **name** (`string`): Human-readable app name
- **version** (`string`): Semantic version (e.g., "1.0.0")
- **prefix** (`string`): URL prefix for mounting (must start with `/`)

**Optional fields:**
- **description** (`string`): Brief description of the app
- **author** (`string`): Author name or organization
- **entry** (`string`): Entry point filename served at the mount root. Default: `"index.html"`

---

## Configuration Options

### Single App: `.with_app()`

Mount a single app from a filesystem path or package resource:

```python
# Mount from filesystem
.with_app("./apps/dashboard")

# Mount from filesystem with custom prefix
.with_app("./apps/dashboard", prefix="/admin")

# Mount from Python package
.with_app(("mycompany.apps", "dashboard"))
```

**Parameters:**
- **path** (`str | Path | tuple[str, str]`): Filesystem path or package tuple
- **prefix** (`str | None`): Override the prefix from manifest.json

### Multiple Apps: `.with_apps()`

Auto-discover and mount all apps in a directory or package:

```python
# Discover from filesystem directory
.with_apps("./apps")

# Discover from Python package
.with_apps(("mycompany.apps", "webapps"))
```

**Parameters:**
- **path** (`str | Path | tuple[str, str]`): Directory path or package tuple

---

## Path Types

### Filesystem Paths

Paths are resolved relative to the current working directory (where the service runs):

```python
# Relative paths
.with_app("./apps/dashboard")
.with_app("apps/dashboard")

# Absolute paths
.with_app("/opt/myproject/apps/dashboard")
```

**Project structure:**
```
myproject/
├── apps/
│   ├── dashboard/
│   │   ├── manifest.json
│   │   └── index.html
│   └── admin/
│       ├── manifest.json
│       └── index.html
├── main.py
└── pyproject.toml
```

**Usage in main.py:**
```python
app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_app("./apps/dashboard")      # Single app
    .with_apps("./apps")               # All apps
    .build()
)
```

### Package Resources

Bundle apps with your Python package using tuple syntax `(package_name, subpath)`:

```python
# Single app from package
.with_app(("mycompany.apps", "dashboard"))

# All apps from package directory
.with_apps(("mycompany.apps", "webapps"))
```

**Package structure:**
```
mycompany/
  apps/
    webapps/
      dashboard/
        manifest.json
        index.html
      admin/
        manifest.json
        index.html
```

**Why use package resources?**
- Ship default apps with your library
- Version apps alongside Python code
- Distribute apps via PyPI
- Easy deployment (no external files needed)

---

## Override Semantics

### Multiple App Calls

Calling `.with_app()` and `.with_apps()` multiple times is **cumulative** - all apps from all calls are combined:

```python
app = (
    BaseServiceBuilder(info=info)
    .with_apps("./apps/set1")      # Discover apps from set1/
    .with_apps("./apps/set2")      # Discover apps from set2/
    .with_app("./apps/custom")     # Add single custom app
    .build()
)
```

All apps from both directories plus the custom app will be mounted.

**This works for all path types:**

```python
# Filesystem paths
.with_apps("./apps/dir1").with_apps("./apps/dir2")

# Package resources
.with_apps(("pkg1", "apps")).with_apps(("pkg2", "apps"))

# Mixed approaches
.with_apps("./apps").with_apps(("mypackage", "bundled_apps"))
```

### Duplicate Prefixes

When multiple apps use the same prefix, **the last one wins**:

```python
app = (
    BaseServiceBuilder(info=info)
    .with_app("apps/dashboard")                    # Mounts at /dashboard
    .with_app("apps/better-dashboard", prefix="/dashboard")  # Replaces first
    .build()
)
```

This applies to duplicates from multiple `.with_app()` or `.with_apps()` calls as well. If `./apps/set1` contains a dashboard at `/dashboard` and `./apps/set2` also contains a dashboard at `/dashboard`, the one from `set2` wins (assuming `set2` was added last).

The service logs a warning when an app overrides another:
```
app.prefix.override prefix=/dashboard replaced_app=Dashboard new_app=BetterDashboard
```

### Landing Page Override

`.with_landing_page()` internally mounts a built-in app at `/`. You can override it:

```python
app = (
    BaseServiceBuilder(info=info)
    .with_landing_page()                  # Built-in landing page at /
    .with_app("apps/custom-home", prefix="/")  # Replace with custom
    .build()
)
```

### Root Apps

Apps can mount at root (`/`), but be aware of a limitation:

Root mounts intercept trailing slash redirects. Use exact paths for API endpoints:
- Correct: `/api/v1/configs`
- Incorrect: `/api/v1/configs/` (may return 404)

API routes always take precedence over apps (routes are registered first).

---

## Restrictions

### Blocked Prefixes

Apps **cannot** mount at `/api` or `/api/**` (reserved for API endpoints):

```python
# This will raise ValueError
.with_app("apps/api-dashboard", prefix="/api/dashboard")
```

### Prefix Format

Prefixes must:
- Start with `/`
- Not contain `..` (path traversal protection)
- Be valid URL paths

```python
# Valid prefixes
.with_app("apps/dashboard", prefix="/dashboard")
.with_app("apps/admin", prefix="/admin/panel")
.with_app("apps/home", prefix="/")

# Invalid prefixes
.with_app("apps/bad", prefix="dashboard")    # Missing leading /
.with_app("apps/bad", prefix="/../../etc")   # Path traversal
```

---

## Testing Apps

### With cURL

```bash
# Test app is accessible
curl http://localhost:8000/dashboard/

# Test app assets
curl http://localhost:8000/dashboard/style.css

# Test API still works
curl http://localhost:8000/api/v1/configs
```

### With Browser

1. Start your service: `fastapi dev your_file.py`
2. Navigate to app: http://localhost:8000/dashboard
3. Check browser console for errors
4. Verify API requests work: http://localhost:8000/api/v1/configs

### In Tests

```python
from starlette.testclient import TestClient

def test_app_is_accessible():
    with TestClient(app) as client:
        # Test app loads
        response = client.get("/dashboard/")
        assert response.status_code == 200
        assert b"Dashboard" in response.content

        # Test app assets
        response = client.get("/dashboard/style.css")
        assert response.status_code == 200

        # Test API still works
        response = client.get("/api/v1/configs")
        assert response.status_code == 200
```

---

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Copy application code
COPY . .

# Install dependencies
RUN pip install -e .

# Copy apps directory
COPY ./apps /app/apps

# Expose port
EXPOSE 8000

# Run service
CMD ["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    volumes:
      # Mount apps directory for development
      - ./apps:/app/apps:ro
    environment:
      - LOG_LEVEL=INFO
```

**Run:**
```bash
docker compose up
```

**Access:**
- App: http://localhost:8000/dashboard
- API: http://localhost:8000/api/v1/configs
- Docs: http://localhost:8000/docs

---

## Kubernetes Deployment

### ConfigMap for Apps

**apps-configmap.yaml:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dashboard-app
data:
  manifest.json: |
    {
      "name": "Dashboard",
      "version": "1.0.0",
      "prefix": "/dashboard"
    }
  index.html: |
    <!DOCTYPE html>
    <html>
      <head><title>Dashboard</title></head>
      <body>
        <h1>Dashboard</h1>
        <div id="app"></div>
      </body>
    </html>
```

### Deployment

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
        image: your-servicekit-app:latest
        ports:
        - containerPort: 8000
        volumeMounts:
        - name: dashboard-app
          mountPath: /app/apps/dashboard
          readOnly: true
      volumes:
      - name: dashboard-app
        configMap:
          name: dashboard-app
```

**service.yaml:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: servicekit-service
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 8000
  selector:
    app: servicekit-service
```

---

## Security

### Path Traversal Protection

Servicekit validates all paths and rejects path traversal attempts:

```python
# All rejected with ValueError
.with_app("apps/../../etc")                          # Prefix traversal
.with_app(("mypackage", "../../../etc"))             # Package traversal

# manifest.json with path traversal also rejected:
{
  "prefix": "/../../admin",     # Rejected
  "entry": "../../../passwd"    # Rejected
}
```

### API Protection

API endpoints are protected from app conflicts:

1. Apps cannot mount at `/api` or `/api/**`
2. Apps are mounted **after** routes, so API routes take precedence
3. Static files never override API endpoints

### Validation

- **Build-time validation**: All errors detected during `.build()` (fail fast)
- **Manifest validation**: Pydantic validates all fields and types
- **File validation**: Entry files must exist before mounting
- **Prefix validation**: Duplicate prefixes detected and logged

---

## Best Practices

### Recommended Practices

- **Separate apps directory**: Keep apps in `./apps` outside source code
- **Version apps**: Use semantic versioning in manifest.json
- **Test locally**: Run `fastapi dev` before deploying
- **Use package resources**: For default/bundled apps in libraries
- **Document prefixes**: List all app URLs in README
- **Keep apps small**: Under 10MB per app for fast loading
- **Use CDN for assets**: For production apps with large assets

### Avoid

- **Hardcoding paths**: Use relative paths, not absolute
- **Path traversal**: Never use `..` in paths or prefixes
- **Large binaries**: Don't bundle videos/large files in apps
- **Duplicate prefixes**: Causes confusion (service logs warnings)
- **API prefix conflicts**: Never mount apps at `/api`
- **Missing manifest**: All apps must have manifest.json

### App Organization

```
apps/
├── dashboard/          # Main dashboard
│   ├── manifest.json
│   └── index.html
├── admin/              # Admin panel
│   ├── manifest.json
│   └── index.html
└── docs/               # Documentation site
    ├── manifest.json
    └── index.html
```

---

## Combining with Other Features

### With Authentication

```python
app = (
    BaseServiceBuilder(info=info)
    .with_auth(
        unauthenticated_paths=[
            "/health",
            "/metrics",
            "/",           # Landing page (root app)
            "/docs",       # API documentation
        ]
    )
    .with_landing_page()    # Public landing page
    .with_app("apps/admin") # Admin panel (requires auth)
    .build()
)
```

### With System Endpoint

Query installed apps programmatically:

```python
app = (
    BaseServiceBuilder(info=info)
    .with_system()          # Enables /api/v1/system/apps
    .with_apps("./apps")
    .build()
)
```

**Test:**
```bash
curl http://localhost:8000/api/v1/system/apps
```

**Response:**
```json
[
  {
    "name": "Dashboard",
    "version": "1.0.0",
    "prefix": "/dashboard",
    "description": "Interactive dashboard",
    "author": "Your Name",
    "entry": "index.html",
    "is_package": false
  }
]
```

---

## Troubleshooting

### App Returns 404

**Problem**: Accessing `/dashboard/` returns 404.

**Solutions**:
1. Verify app directory exists: `ls ./apps/dashboard`
2. Check manifest.json exists: `cat ./apps/dashboard/manifest.json`
3. Verify prefix matches URL: Check `"prefix"` field in manifest
4. Check service logs for mount messages:
   ```
   app.mounted name=Dashboard prefix=/dashboard directory=./apps/dashboard
   ```

### Assets Not Loading

**Problem**: HTML loads but CSS/JS return 404.

**Solutions**:
1. Check file paths in HTML are relative: `<link href="style.css">` not `<link href="/style.css">`
2. Verify assets exist in app directory: `ls ./apps/dashboard/`
3. Test asset URLs: `curl http://localhost:8000/dashboard/style.css`

### Manifest Validation Error

**Problem**: Service fails with "Invalid JSON in manifest.json".

**Solutions**:
1. Validate JSON syntax: `python -m json.tool manifest.json`
2. Check required fields: `name`, `version`, `prefix`
3. Check field types: `version` must be string, not number
4. Remove unknown fields (Pydantic rejects extras)

### App Not Discovered

**Problem**: `.with_apps()` doesn't find the app.

**Solutions**:
1. Verify directory structure: App must be in subdirectory with manifest.json
2. Check manifest.json is valid JSON
3. Review discovery logs for errors:
   ```
   app.discovery.failed directory=./apps/broken error="Entry file 'index.html' not found"
   ```

### Duplicate Prefix Warning

**Problem**: Seeing "app.prefix.override" warnings in logs.

**Solutions**:
1. Check for multiple `.with_app()` calls with same prefix
2. Check multiple manifest.json files with same prefix
3. This is usually intentional (override), but verify it's expected

### API Endpoints Conflict

**Problem**: Cannot mount app because prefix conflicts with API.

**Solutions**:
1. Use different prefix: `/admin` instead of `/api/admin`
2. API endpoints always take precedence (by design)
3. Mount apps at unique, non-API prefixes

---

## Examples

### Basic Dashboard

**apps/dashboard/manifest.json:**
```json
{
  "name": "Dashboard",
  "version": "1.0.0",
  "prefix": "/dashboard",
  "description": "Real-time metrics dashboard"
}
```

**apps/dashboard/index.html:**
```html
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <h1>Dashboard</h1>
    <div id="metrics"></div>
    <script src="script.js"></script>
</body>
</html>
```

**apps/dashboard/script.js:**
```javascript
// Fetch data from your API
fetch('/api/v1/configs')
  .then(response => response.json())
  .then(data => {
    document.getElementById('metrics').innerHTML =
      `<pre>${JSON.stringify(data, null, 2)}</pre>`;
  });
```

### Multi-App Service

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(info=ServiceInfo(id="multi-app-service", display_name="Multi-App Service"))
    .with_health()
    .with_system()
    .with_landing_page()           # Built-in landing at /
    .with_apps("./apps")           # Dashboard, admin, docs
    .build()
)
```

**URLs:**
- `/` - Landing page
- `/dashboard` - Main dashboard
- `/admin` - Admin panel
- `/docs` - API documentation
- `/api/v1/*` - API endpoints

---

## Next Steps

- **SPA Support**: Apps use `html=True` mode (serves index.html for directories)
- **Custom Landing Page**: Override built-in with `.with_app(..., prefix="/")`
- **Package Apps**: Distribute apps via PyPI with your library
- **Authentication**: Combine with `.with_auth()` for protected apps

## Further Reading

For more examples, see:
- `examples/app_hosting/main.py` - Complete app hosting example
- `examples/apps/sample-dashboard/` - Sample dashboard app
- `designs/app-system.md` - Technical design document
- `CLAUDE.md` - Development guide with app system section
