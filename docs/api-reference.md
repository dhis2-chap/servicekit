# API Reference

Complete API documentation for all servicekit modules, classes, and functions.

## Core Infrastructure

Framework-agnostic infrastructure components.

### Database

::: servicekit.database

### Models

::: servicekit.models

### Repository

::: servicekit.repository

### Manager

::: servicekit.manager

### Schemas

::: servicekit.schemas

### Exceptions

::: servicekit.exceptions

### Scheduler

::: servicekit.scheduler

### Types

::: servicekit.types

### Logging

::: servicekit.logging

## FastAPI Layer

FastAPI-specific components for building web services.

### Service Builder

Service builder class for composing FastAPI applications.

#### BaseServiceBuilder

::: servicekit.api.service_builder.BaseServiceBuilder

#### ServiceInfo

::: servicekit.api.service_builder.ServiceInfo

### Routers

Base router classes and generic routers.

#### Router

::: servicekit.api.router.Router

#### CrudRouter

Behavior of the generated endpoints:

- `POST` creates only. Sending an ID that already exists returns `409 Conflict`; use `PUT` to update.
- `PUT` applies exactly the fields present in the request body. An omitted field is left untouched; an explicit
  `null` clears a nullable field.
- `GET` on a collection is ordered by ID (creation order for ULIDs). Pagination is opt-in and requires both
  `page` (>= 1) and `size` (1-100); out-of-range values return `422`, and supplying only one of them returns the
  plain unpaginated list.

::: servicekit.api.crud.CrudRouter

#### CrudPermissions

::: servicekit.api.crud.CrudPermissions

#### HealthRouter

::: servicekit.api.routers.health.HealthRouter

#### JobRouter

::: servicekit.api.routers.job.JobRouter

#### SystemRouter

::: servicekit.api.routers.system.SystemRouter

#### MetricsRouter

::: servicekit.api.routers.metrics.MetricsRouter

### App System

Static web application hosting system.

#### AppLoader

::: servicekit.api.app.AppLoader

#### AppManifest

::: servicekit.api.app.AppManifest

#### App

::: servicekit.api.app.App

#### AppManager

::: servicekit.api.app.AppManager

#### AppInfo

::: servicekit.api.app.AppInfo

### Authentication

API key authentication middleware and utilities.

#### APIKeyMiddleware

::: servicekit.api.auth.APIKeyMiddleware

### Middleware

Error handling and logging middleware.

::: servicekit.api.middleware

### Dependencies

FastAPI dependency injection functions.

Dependencies are **per application**: `get_database`, `get_scheduler`, and
`get_app_manager` take the incoming `Request` and read `request.app.state`, so two
applications running in the same process never share a database or scheduler.

Library code that runs outside a request - a lifespan, a startup hook, a background
task - has no `Request`, so it should capture the objects it needs (for example
`app.state.database`) instead of calling these getters.

::: servicekit.api.dependencies

### Pagination

Pagination helpers for collection endpoints.

::: servicekit.api.pagination

### Utilities

Utility functions for FastAPI applications.

::: servicekit.api.utilities
