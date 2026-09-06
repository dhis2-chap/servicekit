"""FastAPI framework layer - routers, middleware, utilities."""

from .app import App, AppInfo, AppLoader, AppManager, AppManifest, EntryStaticFiles
from .auth import APIKeyMiddleware, load_api_keys_from_env, load_api_keys_from_file, validate_api_key_format
from .crud import CrudPermissions, CrudRouter
from .dependencies import get_app_manager, get_database, get_scheduler, get_session
from .middleware import add_error_handlers, add_logging_middleware, database_error_handler, validation_error_handler
from .pagination import PaginationParams, create_paginated_response
from .router import Router
from .routers import HealthRouter, HealthState, HealthStatus, JobRouter, MetricsRouter, SystemInfo, SystemRouter
from .service_builder import BaseServiceBuilder, JobOptions, ServiceInfo
from .sse import SSE_HEADERS, format_sse_event, format_sse_model_event
from .utilities import build_location_url, run_app

__all__ = [
    # Base router classes
    "Router",
    "CrudRouter",
    "CrudPermissions",
    # Service builder
    "BaseServiceBuilder",
    "JobOptions",
    "ServiceInfo",
    # App system
    "App",
    "AppInfo",
    "AppLoader",
    "AppManifest",
    "AppManager",
    "EntryStaticFiles",
    # Authentication
    "APIKeyMiddleware",
    "load_api_keys_from_env",
    "load_api_keys_from_file",
    "validate_api_key_format",
    # Dependencies
    "get_app_manager",
    "get_database",
    "get_session",
    "get_scheduler",
    # Middleware
    "add_error_handlers",
    "add_logging_middleware",
    "database_error_handler",
    "validation_error_handler",
    # Pagination
    "PaginationParams",
    "create_paginated_response",
    # System routers
    "HealthRouter",
    "HealthState",
    "HealthStatus",
    "JobRouter",
    "MetricsRouter",
    "SystemRouter",
    "SystemInfo",
    # SSE utilities
    "SSE_HEADERS",
    "format_sse_event",
    "format_sse_model_event",
    # Utilities
    "build_location_url",
    "run_app",
]
