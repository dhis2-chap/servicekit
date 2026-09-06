# Servicekit

[![CI](https://github.com/dhis2-chap/servicekit/actions/workflows/ci.yml/badge.svg)](https://github.com/dhis2-chap/servicekit/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/servicekit)](https://pypi.org/project/servicekit/)
[![codecov](https://codecov.io/gh/dhis2-chap/servicekit/branch/main/graph/badge.svg)](https://codecov.io/gh/dhis2-chap/servicekit)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue.svg)](https://dhis2-chap.github.io/servicekit/)

> Async SQLAlchemy framework with FastAPI integration - reusable foundation for building data services

Servicekit is a framework-agnostic core library providing foundational infrastructure for building async Python services with FastAPI and SQLAlchemy.

## Features

- **Database Layer**: Async SQLAlchemy with SQLite support, connection pooling, and automatic migrations
- **Repository Pattern**: Generic repository base classes for data access
- **Manager Pattern**: Business logic layer with lifecycle hooks
- **CRUD API**: Auto-generated REST endpoints with full CRUD operations
- **Authentication**: API key middleware with file and environment variable support
- **Job Scheduling**: Async job scheduler with concurrency control
- **App Hosting**: Mount static web applications alongside your API
- **Monitoring**: Prometheus metrics and OpenTelemetry integration
- **Health Checks**: Flexible health check system with SSE streaming support
- **Error Handling**: RFC 9457 Problem Details for HTTP APIs
- **Logging**: Structured logging with request context

## Installation

```bash
pip install servicekit
```

## Quick Start

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_health()
    .with_database("sqlite+aiosqlite:///./data.db")
    .build()
)
```

## Architecture

```
servicekit/
├── database.py       # Database, SqliteDatabase, SqliteDatabaseBuilder
├── models.py         # Base, Entity ORM classes
├── repository.py     # Repository, BaseRepository
├── manager.py        # Manager, BaseManager
├── schemas.py        # EntityIn, EntityOut, PaginatedResponse
├── scheduler.py      # JobScheduler, AIOJobScheduler
├── exceptions.py     # Error classes
├── logging.py        # Structured logging
├── types.py          # ULIDType, JsonSafe
└── api/              # FastAPI framework layer
    ├── router.py     # Router base class
    ├── crud.py       # CrudRouter, CrudPermissions
    ├── auth.py       # API key authentication
    ├── app.py        # Static app hosting
    ├── middleware.py # Error handlers, logging
    └── routers/      # Health, Jobs, System, Metrics
```

## Key Components

### BaseServiceBuilder

```python
from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(info=ServiceInfo(id="my-service", display_name="My Service"))
    .with_health()                    # Health check endpoint
    .with_database(url)               # Database configuration
    .with_jobs(max_concurrency=10)   # Job scheduler
    .with_auth()                      # API key authentication
    .with_monitoring()                # Prometheus metrics
    .with_app("./webapp")             # Static web app
    .include_router(custom_router)   # Custom routes
    .build()
)
```

### Database Migrations

File-based databases run Alembic migrations on `init()` by default; in-memory databases create tables
directly from the ORM metadata. The migration bundled with servicekit is a framework baseline: it creates
only the `alembic_version` table and no application tables. Applications that define their own entities must
either point migrations at their own migration directory or disable migrations and create tables directly.

```python
from pathlib import Path

from servicekit import SqliteDatabaseBuilder, get_alembic_dir

# Application-owned migrations
database = (
    SqliteDatabaseBuilder.from_file("app.db")
    .with_migrations(enabled=True, alembic_dir=Path("alembic"))
    .build()
)

# No migrations - create tables directly from ORM metadata
database = SqliteDatabaseBuilder.from_file("app.db").with_migrations(enabled=False).build()

# Path to the migration environment shipped inside the servicekit package
bundled_migrations = get_alembic_dir()
```

### Repository Pattern

```python
from servicekit import BaseRepository, Entity
from sqlalchemy.orm import Mapped, mapped_column

class User(Entity):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column()
    email: Mapped[str] = mapped_column()

class UserRepository(BaseRepository[User, ULID]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, User)
```

### CRUD Router

```python
from servicekit.api import CrudRouter, CrudPermissions

router = CrudRouter.create(
    prefix="/api/v1/users",
    tags=["Users"],
    entity_in_type=UserIn,
    entity_out_type=UserOut,
    manager_factory=get_user_manager,
    permissions=CrudPermissions(create=True, read=True, update=True, delete=False)
)
```


## Examples

See the `examples/` directory for complete working examples:

- `core_api/main.py` - Basic CRUD service
- `job_scheduler/main.py` - Background job execution
- `app_hosting/main.py` - Hosting static web apps
- `auth/main.py` - API key authentication
- `monitoring/main.py` - Prometheus metrics

## Documentation

See `docs/` for comprehensive guides and API reference.

## Testing

```bash
make test      # Run tests
make lint      # Run linter
make coverage  # Test coverage
```

## License

AGPL-3.0-or-later

## Related Projects

- **[chapkit](https://github.com/dhis2-chap/chapkit)** - Domain modules (artifacts, configs, tasks, ML workflows) built on servicekit ([docs](https://dhis2-chap.github.io/chapkit))
