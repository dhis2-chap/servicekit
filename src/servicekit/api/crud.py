"""CRUD router base class for standard REST operations."""

from dataclasses import dataclass
from typing import Annotated, Any, Callable, cast

from fastapi import Depends, Query, Request, Response, status
from pydantic import BaseModel
from ulid import ULID

from servicekit.api.router import Router
from servicekit.manager import Manager
from servicekit.schemas import PaginatedResponse, ProblemDetail

# OpenAPI response documentation shared by CRUD routes
_CONFLICT_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {
        "model": ProblemDetail,
        "description": "An entity with the supplied id already exists or a database constraint was violated",
    }
}

_NOT_FOUND_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ProblemDetail,
        "description": "No entity exists with the supplied id",
    }
}

# Type alias for manager factory function
type ManagerFactory[InSchemaT: BaseModel, OutSchemaT: BaseModel] = Callable[..., Manager[InSchemaT, OutSchemaT, ULID]]


@dataclass(slots=True)
class CrudPermissions:
    """Permissions configuration for CRUD operations."""

    create: bool = True
    read: bool = True
    update: bool = True
    delete: bool = True


class CrudRouter[InSchemaT: BaseModel, OutSchemaT: BaseModel](Router):
    """Router base class for standard REST CRUD operations."""

    def __init__(
        self,
        prefix: str,
        tags: list[str],
        entity_in_type: type[InSchemaT],
        entity_out_type: type[OutSchemaT],
        manager_factory: ManagerFactory[InSchemaT, OutSchemaT],
        *,
        permissions: CrudPermissions | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize CRUD router with entity types and manager factory."""
        self.manager_factory = manager_factory
        self.entity_in_type = entity_in_type
        self.entity_out_type = entity_out_type
        self._permissions = permissions or CrudPermissions()
        super().__init__(prefix=prefix, tags=tags, **kwargs)

    def _register_routes(self) -> None:
        """Register CRUD routes based on permissions."""
        manager_dependency, manager_annotation = self._manager_dependency()
        perms = self._permissions
        if perms.create:
            self._register_create_route(manager_dependency, manager_annotation)
        if perms.read:
            self._register_find_all_route(manager_dependency, manager_annotation)
            self._register_find_by_id_route(manager_dependency, manager_annotation)
            self._register_schema_route()
            self._register_stats_route(manager_dependency, manager_annotation)
        if perms.update:
            self._register_update_route(manager_dependency, manager_annotation)
        if perms.delete:
            self._register_delete_route(manager_dependency, manager_annotation)

    def register_entity_operation(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        http_method: str = "GET",
        response_model: type[Any] | None = None,
        status_code: int | None = None,
        summary: str | None = None,
        description: str | None = None,
    ) -> None:
        """Register a custom entity operation with $ prefix.

        Entity operations are automatically inserted before generic {entity_id} routes
        to ensure proper route matching (e.g., /{entity_id}/$validate should match
        before /{entity_id}).
        """
        route = f"/{{entity_id}}/${name}"
        route_kwargs: dict[str, Any] = {}

        if response_model is not None:
            route_kwargs["response_model"] = response_model
        if status_code is not None:
            route_kwargs["status_code"] = status_code
        if summary is not None:
            route_kwargs["summary"] = summary
        if description is not None:
            route_kwargs["description"] = description

        # Register the route with the appropriate HTTP method
        http_method_lower = http_method.lower()
        if http_method_lower == "get":
            self.router.get(route, **route_kwargs)(handler)
        elif http_method_lower == "post":
            self.router.post(route, **route_kwargs)(handler)
        elif http_method_lower == "put":
            self.router.put(route, **route_kwargs)(handler)
        elif http_method_lower == "patch":
            self.router.patch(route, **route_kwargs)(handler)
        elif http_method_lower == "delete":
            self.router.delete(route, **route_kwargs)(handler)
        else:
            raise ValueError(f"Unsupported HTTP method: {http_method}")

        # Move the just-added route to before generic parametric routes
        # Entity operations like /{entity_id}/$validate should match before /{entity_id}
        if len(self.router.routes) > 1:
            new_route = self.router.routes.pop()
            insert_index = self._find_generic_parametric_route_index()
            self.router.routes.insert(insert_index, new_route)

    def register_collection_operation(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        http_method: str = "GET",
        response_model: type[Any] | None = None,
        status_code: int | None = None,
        summary: str | None = None,
        description: str | None = None,
    ) -> None:
        """Register a custom collection operation with $ prefix.

        Collection operations are automatically inserted before parametric {entity_id} routes
        to ensure proper route matching (e.g., /$stats should match before /{entity_id}).
        """
        route = f"/${name}"
        route_kwargs: dict[str, Any] = {}

        if response_model is not None:
            route_kwargs["response_model"] = response_model
        if status_code is not None:
            route_kwargs["status_code"] = status_code
        if summary is not None:
            route_kwargs["summary"] = summary
        if description is not None:
            route_kwargs["description"] = description

        # Register the route with the appropriate HTTP method
        http_method_lower = http_method.lower()
        if http_method_lower == "get":
            self.router.get(route, **route_kwargs)(handler)
        elif http_method_lower == "post":
            self.router.post(route, **route_kwargs)(handler)
        elif http_method_lower == "put":
            self.router.put(route, **route_kwargs)(handler)
        elif http_method_lower == "patch":
            self.router.patch(route, **route_kwargs)(handler)
        elif http_method_lower == "delete":
            self.router.delete(route, **route_kwargs)(handler)
        else:
            raise ValueError(f"Unsupported HTTP method: {http_method}")

        # Move the just-added route to before parametric routes
        # FastAPI appends to routes list, so the last route is the one we just added
        if len(self.router.routes) > 1:
            new_route = self.router.routes.pop()  # Remove the route we just added
            # Find the first parametric route and insert before it
            insert_index = self._find_parametric_route_index()
            self.router.routes.insert(insert_index, new_route)

    # Route registration helpers --------------------------------------

    def _register_create_route(self, manager_dependency: Any, manager_annotation: Any) -> None:
        entity_in_annotation: Any = self.entity_in_type
        entity_out_annotation: Any = self.entity_out_type
        router_prefix = self.router.prefix

        @self.router.post(
            "",
            status_code=status.HTTP_201_CREATED,
            response_model=entity_out_annotation,
            responses=_CONFLICT_RESPONSES,
        )
        async def create(
            entity_in: InSchemaT,
            request: Request,
            response: Response,
            manager: Manager[InSchemaT, OutSchemaT, ULID] = manager_dependency,
        ) -> OutSchemaT:
            from .utilities import build_location_url

            created_entity = await manager.create(entity_in)
            entity_id = getattr(created_entity, "id")
            response.headers["Location"] = build_location_url(request, f"{router_prefix}/{entity_id}")
            return created_entity

        self._annotate_manager(create, manager_annotation)
        create.__annotations__["entity_in"] = entity_in_annotation
        create.__annotations__["return"] = entity_out_annotation

    def _register_find_all_route(self, manager_dependency: Any, manager_annotation: Any) -> None:
        from .pagination import PaginationParams, create_paginated_response

        entity_out_annotation: Any = self.entity_out_type
        collection_response_model: Any = list[entity_out_annotation] | PaginatedResponse[entity_out_annotation]

        @self.router.get("", response_model=collection_response_model)
        async def find_all(
            pagination: Annotated[PaginationParams, Query()],
            manager: Manager[InSchemaT, OutSchemaT, ULID] = manager_dependency,
        ) -> list[OutSchemaT] | PaginatedResponse[OutSchemaT]:
            """List entities; pagination is opt-in and requires both page (>= 1) and size (1-100).

            Supplying only one of them returns the plain unpaginated list.
            """
            if pagination.is_paginated():
                page = cast(int, pagination.page)
                size = cast(int, pagination.size)
                items, total = await manager.find_paginated(page, size)
                return create_paginated_response(items, total, page, size)
            return await manager.find_all()

        self._annotate_manager(find_all, manager_annotation)
        find_all.__annotations__["return"] = list[entity_out_annotation] | PaginatedResponse[entity_out_annotation]

    def _register_find_by_id_route(self, manager_dependency: Any, manager_annotation: Any) -> None:
        entity_out_annotation: Any = self.entity_out_type
        router_prefix = self.router.prefix

        @self.router.get("/{entity_id}", response_model=entity_out_annotation, responses=_NOT_FOUND_RESPONSES)
        async def find_by_id(
            entity_id: str,
            manager: Manager[InSchemaT, OutSchemaT, ULID] = manager_dependency,
        ) -> OutSchemaT:
            from servicekit.exceptions import NotFoundError

            ulid_id = self._parse_ulid(entity_id)
            entity = await manager.find_by_id(ulid_id)
            if entity is None:
                raise NotFoundError(
                    f"Entity with id {entity_id} not found",
                    instance=f"{router_prefix}/{entity_id}",
                )
            return entity

        self._annotate_manager(find_by_id, manager_annotation)
        find_by_id.__annotations__["return"] = entity_out_annotation

    def _register_update_route(self, manager_dependency: Any, manager_annotation: Any) -> None:
        entity_in_annotation: Any = self.entity_in_type
        entity_out_annotation: Any = self.entity_out_type
        router_prefix = self.router.prefix

        @self.router.put("/{entity_id}", response_model=entity_out_annotation, responses=_NOT_FOUND_RESPONSES)
        async def update(
            entity_id: str,
            entity_in: InSchemaT,
            manager: Manager[InSchemaT, OutSchemaT, ULID] = manager_dependency,
        ) -> OutSchemaT:
            from servicekit.exceptions import NotFoundError

            ulid_id = self._parse_ulid(entity_id)
            if not await manager.exists_by_id(ulid_id):
                raise NotFoundError(
                    f"Entity with id {entity_id} not found",
                    instance=f"{router_prefix}/{entity_id}",
                )
            entity_with_id = entity_in.model_copy(update={"id": ulid_id})
            return await manager.save(entity_with_id)

        self._annotate_manager(update, manager_annotation)
        update.__annotations__["entity_in"] = entity_in_annotation
        update.__annotations__["return"] = entity_out_annotation

    def _register_delete_route(self, manager_dependency: Any, manager_annotation: Any) -> None:
        router_prefix = self.router.prefix

        @self.router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_NOT_FOUND_RESPONSES)
        async def delete_by_id(
            entity_id: str,
            manager: Manager[InSchemaT, OutSchemaT, ULID] = manager_dependency,
        ) -> None:
            from servicekit.exceptions import NotFoundError

            ulid_id = self._parse_ulid(entity_id)
            if not await manager.exists_by_id(ulid_id):
                raise NotFoundError(
                    f"Entity with id {entity_id} not found",
                    instance=f"{router_prefix}/{entity_id}",
                )
            await manager.delete_by_id(ulid_id)

        self._annotate_manager(delete_by_id, manager_annotation)

    def _register_schema_route(self) -> None:
        """Register JSON schema endpoint for the entity output type."""
        entity_out_type = self.entity_out_type

        async def get_schema() -> dict[str, Any]:
            return entity_out_type.model_json_schema()

        self.register_collection_operation(
            name="schema",
            handler=get_schema,
            http_method="GET",
            response_model=dict[str, Any],
        )

    def _register_stats_route(self, manager_dependency: Any, manager_annotation: Any) -> None:
        """Register collection statistics endpoint."""
        from servicekit.schemas import CollectionStats

        async def get_stats(
            manager: Manager[InSchemaT, OutSchemaT, ULID] = manager_dependency,
        ) -> CollectionStats:
            """Get collection statistics."""
            return await manager.get_stats()

        self._annotate_manager(get_stats, manager_annotation)

        self.register_collection_operation(
            name="stats",
            handler=get_stats,
            http_method="GET",
            response_model=CollectionStats,
            summary="Get collection statistics",
            description="Returns statistics about the collection including total entity count.",
        )

    # Helper utilities -------------------------------------------------

    def _manager_dependency(self) -> tuple[Any, Any]:
        manager_dependency = Depends(self.manager_factory)
        manager_annotation: Any = Manager[Any, Any, ULID]
        return manager_dependency, manager_annotation

    def _annotate_manager(self, endpoint: Any, manager_annotation: Any) -> None:
        endpoint.__annotations__["manager"] = manager_annotation

    def _parse_ulid(self, entity_id: str) -> ULID:
        from servicekit.exceptions import InvalidULIDError

        try:
            return ULID.from_str(entity_id)
        except ValueError as e:
            raise InvalidULIDError(
                f"Invalid ULID format: {entity_id}",
                instance=f"{self.router.prefix}/{entity_id}",
            ) from e

    def _find_parametric_route_index(self) -> int:
        """Find the index of the first parametric route containing {entity_id}.

        Returns the index where collection operations should be inserted to ensure
        they're matched before parametric routes.
        """
        for i, route in enumerate(self.router.routes):
            route_path = getattr(route, "path", "")
            if "{entity_id}" in route_path:
                return i
        # If no parametric route found, append at the end
        return len(self.router.routes)

    def _find_generic_parametric_route_index(self) -> int:
        """Find the index of the first generic parametric route (/{entity_id} without $).

        Returns the index where entity operations should be inserted to ensure
        they're matched before generic routes like GET/PUT/DELETE /{entity_id}.
        """
        for i, route in enumerate(self.router.routes):
            route_path = getattr(route, "path", "")
            # Match routes like /{entity_id} but not /{entity_id}/$operation
            if "{entity_id}" in route_path and "/$" not in route_path:
                return i
        # If no generic parametric route found, append at the end
        return len(self.router.routes)
