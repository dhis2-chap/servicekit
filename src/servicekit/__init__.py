"""Core framework components - generic interfaces and base classes."""

# ruff: noqa: F401

# Read version from package metadata - must be before internal imports
try:
    from importlib.metadata import version as _get_version

    __version__ = _get_version("servicekit")
except Exception:
    __version__ = "unknown"

# Base infrastructure (framework-agnostic)
from .database import Database, SqliteDatabase, SqliteDatabaseBuilder, get_alembic_dir
from .exceptions import (
    BadRequestError,
    ConflictError,
    ErrorType,
    ForbiddenError,
    InvalidULIDError,
    NotFoundError,
    ServicekitException,
    UnauthorizedError,
    ValidationError,
)
from .logging import add_request_context, clear_request_context, configure_logging, get_logger, reset_request_context
from .manager import BaseManager, LifecycleHooks, Manager
from .models import Base, Entity
from .repository import BaseRepository, Repository
from .scheduler import InMemoryScheduler, Scheduler
from .schemas import (
    BulkOperationError,
    BulkOperationResult,
    EntityIn,
    EntityOut,
    JobRecord,
    JobStatus,
    PaginatedResponse,
    ProblemDetail,
)
from .types import JsonSafe, ULIDType

__all__ = [
    # Version
    "__version__",
    # Base infrastructure
    "Database",
    "SqliteDatabase",
    "SqliteDatabaseBuilder",
    "get_alembic_dir",
    "Repository",
    "BaseRepository",
    "Manager",
    "LifecycleHooks",
    "BaseManager",
    # ORM and types
    "Base",
    "Entity",
    "ULIDType",
    "JsonSafe",
    # Schemas
    "EntityIn",
    "EntityOut",
    "PaginatedResponse",
    "BulkOperationResult",
    "BulkOperationError",
    "ProblemDetail",
    "JobRecord",
    "JobStatus",
    # Job scheduling
    "Scheduler",
    "InMemoryScheduler",
    # Exceptions
    "ErrorType",
    "ServicekitException",
    "NotFoundError",
    "ValidationError",
    "ConflictError",
    "InvalidULIDError",
    "BadRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    # Logging
    "configure_logging",
    "get_logger",
    "add_request_context",
    "clear_request_context",
    "reset_request_context",
]
