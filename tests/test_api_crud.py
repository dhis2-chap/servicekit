"""Tests for the CRUD router abstraction."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from servicekit.schemas import CollectionStats

import pytest
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel
from ulid import ULID

from servicekit.api.crud import CrudPermissions, CrudRouter
from servicekit.exceptions import ConflictError
from servicekit.manager import Manager


class ItemIn(BaseModel):
    """Input schema with optional ID to support updates."""

    name: str
    description: str | None = None
    id: ULID | None = None


class ItemOut(BaseModel):
    """Output schema with ULID identifier."""

    id: ULID
    name: str
    description: str | None = None


class FakeManager(Manager[ItemIn, ItemOut, ULID]):
    """Minimal async manager used for exercising router behaviour."""

    def __init__(self) -> None:
        self.entities: dict[ULID, ItemOut] = {}
        self.find_all_calls = 0
        self.find_paginated_calls = 0

    async def create(self, data: ItemIn) -> ItemOut:
        if data.id is not None and data.id in self.entities:
            raise ConflictError(f"Entity with id {data.id} already exists")
        return await self.save(data)

    async def save(self, data: ItemIn) -> ItemOut:
        entity_id = data.id or ULID()
        fields = data.model_dump(exclude_unset=True)
        existing = self.entities.get(entity_id)
        if existing is not None:
            name = fields.get("name", existing.name)
            description = fields["description"] if "description" in fields else existing.description
        else:
            name = data.name
            description = data.description
        entity = ItemOut(id=entity_id, name=name, description=description)
        self.entities[entity_id] = entity
        return entity

    async def find_all(self) -> list[ItemOut]:
        self.find_all_calls += 1
        return list(self.entities.values())

    async def find_paginated(self, page: int, size: int) -> tuple[list[ItemOut], int]:
        self.find_paginated_calls += 1
        all_items = list(self.entities.values())
        offset = (page - 1) * size
        paginated_items = all_items[offset : offset + size]
        return paginated_items, len(all_items)

    async def find_all_by_id(self, ids: Sequence[ULID]) -> list[ItemOut]:
        id_set = set(ids)
        return [entity for entity_id, entity in self.entities.items() if entity_id in id_set]

    async def find_by_id(self, id: ULID) -> ItemOut | None:
        return self.entities.get(id)

    async def exists_by_id(self, id: ULID) -> bool:
        return id in self.entities

    async def delete_by_id(self, id: ULID) -> None:
        self.entities.pop(id, None)

    async def delete_all(self) -> None:
        self.entities.clear()

    async def delete_all_by_id(self, ids: Sequence[ULID]) -> None:
        for entity_id in ids:
            self.entities.pop(entity_id, None)

    async def count(self) -> int:
        return len(self.entities)

    async def save_all(self, items: Iterable[ItemIn]) -> list[ItemOut]:
        return [await self.save(item) for item in items]

    async def get_stats(self) -> CollectionStats:
        """Get collection statistics."""
        from servicekit.schemas import CollectionStats

        return CollectionStats(total=len(self.entities))


def _build_router(manager: FakeManager) -> CrudRouter[ItemIn, ItemOut]:
    def manager_factory() -> Manager[ItemIn, ItemOut, ULID]:
        return manager

    return CrudRouter[ItemIn, ItemOut](
        prefix="/items",
        tags=["items"],
        entity_in_type=ItemIn,
        entity_out_type=ItemOut,
        manager_factory=manager_factory,
    )


@pytest.fixture
def crud_client() -> tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]]:
    from servicekit.api.middleware import add_error_handlers

    manager = FakeManager()
    router = _build_router(manager)
    app = FastAPI()
    add_error_handlers(app)
    app.include_router(router.router)
    return TestClient(app), manager, router


@pytest.fixture
def operations_client() -> tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]]:
    from servicekit.api.middleware import add_error_handlers

    manager = FakeManager()
    router = _build_router(manager)

    async def echo_entity(
        entity_id: str,
        manager_dep: FakeManager = Depends(router.manager_factory),
    ) -> ItemOut:
        ulid_id = router._parse_ulid(entity_id)
        entity = await manager_dep.find_by_id(ulid_id)
        if entity is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
        return entity

    router.register_entity_operation(
        "echo",
        echo_entity,
        response_model=ItemOut,
        summary="Echo entity",
        description="Return the entity if it exists",
    )

    async def tally(
        manager_dep: FakeManager = Depends(router.manager_factory),
    ) -> dict[str, int]:
        return {"count": len(manager_dep.entities)}

    router.register_collection_operation(
        "tally",
        tally,
        http_method="POST",
        status_code=status.HTTP_202_ACCEPTED,
        summary="Count items",
        description="Return the number of stored items",
    )

    app = FastAPI()
    add_error_handlers(app)
    app.include_router(router.router)
    return TestClient(app), manager, router


def test_create_persists_entity(crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]]) -> None:
    client, manager, _ = crud_client

    response = client.post("/items/", json={"name": "widget", "description": "first"})

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "widget"
    assert data["description"] == "first"
    assert len(manager.entities) == 1
    stored = next(iter(manager.entities.values()))
    assert stored.name == "widget"
    assert str(stored.id) == data["id"]


def test_create_returns_location_header(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, _, _ = crud_client

    response = client.post("/items/", json={"name": "widget", "description": "first"})

    assert response.status_code == status.HTTP_201_CREATED
    assert "Location" in response.headers
    data = response.json()
    entity_id = data["id"]
    expected_location = f"http://testserver/items/{entity_id}"
    assert response.headers["Location"] == expected_location


def test_find_all_returns_all_entities(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, _, _ = crud_client
    client.post("/items/", json={"name": "alpha"})
    client.post("/items/", json={"name": "beta"})

    response = client.get("/items/")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert {item["name"] for item in payload} == {"alpha", "beta"}


def test_find_by_id_returns_entity(crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]]) -> None:
    client, _, _ = crud_client
    created = client.post("/items/", json={"name": "stored"}).json()

    response = client.get(f"/items/{created['id']}")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "stored"


def test_find_by_id_returns_404_when_missing(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, _, _ = crud_client
    missing_id = str(ULID())

    response = client.get(f"/items/{missing_id}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in response.json()["detail"]


def test_find_by_id_rejects_invalid_ulid(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, _, _ = crud_client

    response = client.get("/items/not-a-ulid")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid ULID format" in response.json()["detail"]


def test_update_replaces_entity_values(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, manager, _ = crud_client
    created = client.post("/items/", json={"name": "original", "description": "old"}).json()

    response = client.put(f"/items/{created['id']}", json={"name": "updated"})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["name"] == "updated"
    ulid_id = ULID.from_str(created["id"])
    assert manager.entities[ulid_id].name == "updated"


def test_update_returns_404_when_entity_missing(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, _, _ = crud_client
    missing = str(ULID())

    response = client.put(f"/items/{missing}", json={"name": "irrelevant"})

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in response.json()["detail"]


def test_update_rejects_invalid_ulid(crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]]) -> None:
    client, _, _ = crud_client

    response = client.put("/items/not-a-ulid", json={"name": "invalid"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_delete_by_id_removes_entity(crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]]) -> None:
    client, manager, _ = crud_client
    created = client.post("/items/", json={"name": "to-delete"}).json()
    entity_id = ULID.from_str(created["id"])

    response = client.delete(f"/items/{created['id']}")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert entity_id not in manager.entities


def test_delete_by_id_returns_404_when_entity_missing(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, _, _ = crud_client

    response = client.delete(f"/items/{str(ULID())}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_by_id_rejects_invalid_ulid(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, _, _ = crud_client

    response = client.delete("/items/not-a-ulid")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_entity_operation_uses_registered_handler(
    operations_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, _, router = operations_client
    created = client.post("/items/", json={"name": "entity"}).json()

    response = client.get(f"/items/{created['id']}/$echo")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == created["id"]
    route = next(
        route
        for route in router.router.routes
        if isinstance(route, APIRoute) and route.path == "/items/{entity_id}/$echo"
    )
    assert isinstance(route, APIRoute)
    assert route.summary == "Echo entity"


def test_entity_operation_validates_ulid_before_handler(
    operations_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, _, _ = operations_client

    response = client.get("/items/not-a-ulid/$echo")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_collection_operation_supports_custom_http_method(
    operations_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    client, _, router = operations_client
    client.post("/items/", json={"name": "counted"})

    response = client.post("/items/$tally")

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json() == {"count": 1}
    route = next(
        route for route in router.router.routes if isinstance(route, APIRoute) and route.path == "/items/$tally"
    )
    assert isinstance(route, APIRoute)
    assert route.summary == "Count items"


def test_register_entity_operation_rejects_unknown_http_method() -> None:
    manager = FakeManager()
    router = _build_router(manager)

    async def handler(entity_id: str) -> None:
        return None

    with pytest.raises(ValueError):
        router.register_entity_operation("invalid", handler, http_method="INVALID")


def test_register_collection_operation_rejects_unknown_http_method() -> None:
    manager = FakeManager()
    router = _build_router(manager)

    async def handler() -> None:
        return None

    with pytest.raises(ValueError):
        router.register_collection_operation("invalid", handler, http_method="INVALID")


def test_entity_operation_supports_patch_method() -> None:
    from servicekit.api.middleware import add_error_handlers

    manager = FakeManager()
    router = _build_router(manager)

    async def partial_update(
        entity_id: str,
        name: str,
        manager_dep: FakeManager = Depends(router.manager_factory),
    ) -> ItemOut:
        ulid_id = router._parse_ulid(entity_id)
        entity = await manager_dep.find_by_id(ulid_id)
        if entity is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        entity.name = name
        return entity

    router.register_entity_operation(
        "partial-update",
        partial_update,
        http_method="PATCH",
        response_model=ItemOut,
        summary="Partially update entity",
    )

    app = FastAPI()
    add_error_handlers(app)
    app.include_router(router.router)
    client = TestClient(app)

    created = client.post("/items/", json={"name": "original"}).json()
    response = client.patch(f"/items/{created['id']}/$partial-update?name=updated")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "updated"
    route = next(
        route
        for route in router.router.routes
        if isinstance(route, APIRoute) and route.path == "/items/{entity_id}/$partial-update"
    )
    assert route.methods is not None and "PATCH" in route.methods


def test_collection_operation_supports_patch_method() -> None:
    from servicekit.api.middleware import add_error_handlers

    manager = FakeManager()
    router = _build_router(manager)

    async def bulk_update(
        suffix: str,
        manager_dep: FakeManager = Depends(router.manager_factory),
    ) -> dict[str, int]:
        count = 0
        for entity in manager_dep.entities.values():
            entity.name = f"{entity.name}_{suffix}"
            count += 1
        return {"updated": count}

    router.register_collection_operation(
        "bulk-update",
        bulk_update,
        http_method="PATCH",
        status_code=status.HTTP_200_OK,
        summary="Bulk update items",
    )

    app = FastAPI()
    add_error_handlers(app)
    app.include_router(router.router)
    client = TestClient(app)

    client.post("/items/", json={"name": "item1"})
    client.post("/items/", json={"name": "item2"})

    response = client.patch("/items/$bulk-update?suffix=modified")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["updated"] == 2
    route = next(
        route for route in router.router.routes if isinstance(route, APIRoute) and route.path == "/items/$bulk-update"
    )
    assert route.methods is not None and "PATCH" in route.methods


def test_create_rejects_existing_id_with_conflict(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    """POST with an already used id returns 409 and leaves the original entity untouched."""
    client, manager, _ = crud_client
    created = client.post("/items/", json={"name": "original", "description": "first"}).json()

    response = client.post("/items/", json={"id": created["id"], "name": "overwrite", "description": "second"})

    assert response.status_code == status.HTTP_409_CONFLICT
    stored = manager.entities[ULID.from_str(created["id"])]
    assert stored.name == "original"
    assert stored.description == "first"


def test_create_rejects_existing_id_when_update_is_disabled() -> None:
    """POST cannot overwrite an entity when the router forbids updates."""
    from servicekit.api.middleware import add_error_handlers

    manager = FakeManager()

    def manager_factory() -> Manager[ItemIn, ItemOut, ULID]:
        return manager

    router = CrudRouter[ItemIn, ItemOut](
        prefix="/items",
        tags=["items"],
        entity_in_type=ItemIn,
        entity_out_type=ItemOut,
        manager_factory=manager_factory,
        permissions=CrudPermissions(create=True, update=False),
    )
    app = FastAPI()
    add_error_handlers(app)
    app.include_router(router.router)
    client = TestClient(app)

    created = client.post("/items/", json={"name": "original"}).json()
    response = client.post("/items/", json={"id": created["id"], "name": "overwrite"})

    assert response.status_code == status.HTTP_409_CONFLICT
    assert manager.entities[ULID.from_str(created["id"])].name == "original"
    update_response = client.put(f"/items/{created['id']}", json={"name": "nope"})
    assert update_response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_update_with_explicit_null_clears_field(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    """PUT with an explicit null clears a nullable field."""
    client, manager, _ = crud_client
    created = client.post("/items/", json={"name": "widget", "description": "present"}).json()

    response = client.put(f"/items/{created['id']}", json={"name": "widget", "description": None})

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["description"] is None
    assert manager.entities[ULID.from_str(created["id"])].description is None


def test_update_without_field_keeps_value(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    """PUT without a field leaves the stored value untouched."""
    client, manager, _ = crud_client
    created = client.post("/items/", json={"name": "widget", "description": "present"}).json()

    response = client.put(f"/items/{created['id']}", json={"name": "renamed"})

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["description"] == "present"
    assert manager.entities[ULID.from_str(created["id"])].name == "renamed"


@pytest.mark.parametrize("query", ["page=0&size=10", "page=1&size=101", "page=1&size=-1"])
def test_find_all_rejects_out_of_bounds_pagination(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
    query: str,
) -> None:
    """Pagination bounds are enforced before the manager is called."""
    client, manager, _ = crud_client
    client.post("/items/", json={"name": "alpha"})
    manager.find_all_calls = 0

    response = client.get(f"/items/?{query}")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert manager.find_all_calls == 0
    assert manager.find_paginated_calls == 0


def test_find_all_returns_paginated_response(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    """Supplying both page and size returns a paginated response."""
    client, _, _ = crud_client
    for name in ("alpha", "beta", "gamma"):
        client.post("/items/", json={"name": name})

    response = client.get("/items/?page=1&size=2")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["size"] == 2
    assert len(payload["items"]) == 2


def test_find_all_with_only_page_returns_plain_list(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    """Supplying only one pagination parameter returns the unpaginated list."""
    client, _, _ = crud_client
    client.post("/items/", json={"name": "alpha"})

    response = client.get("/items/?page=2")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 1


def test_find_all_documents_pagination_query_parameters(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    """Pagination bounds are visible in the generated OpenAPI schema."""
    client, _, _ = crud_client

    schema = client.get("/openapi.json").json()
    parameters = schema["paths"]["/items"]["get"]["parameters"]
    by_name = {parameter["name"]: parameter for parameter in parameters}

    assert by_name["page"]["in"] == "query"
    assert by_name["size"]["in"] == "query"
    page_schema = next(entry for entry in by_name["page"]["schema"]["anyOf"] if entry.get("type") == "integer")
    size_schema = next(entry for entry in by_name["size"]["schema"]["anyOf"] if entry.get("type") == "integer")
    assert page_schema["minimum"] == 1
    assert size_schema["minimum"] == 1
    assert size_schema["maximum"] == 100


def test_create_documents_conflict_response(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    """The create route documents a 409 Problem Details response."""
    client, _, _ = crud_client

    schema = client.get("/openapi.json").json()
    responses = schema["paths"]["/items"]["post"]["responses"]

    assert "409" in responses
    content = responses["409"]["content"]["application/json"]
    assert content["schema"]["$ref"].endswith("/ProblemDetail")


def test_entity_routes_document_not_found_response(
    crud_client: tuple[TestClient, FakeManager, CrudRouter[ItemIn, ItemOut]],
) -> None:
    """The entity routes document a 404 Problem Details response."""
    client, _, _ = crud_client

    schema = client.get("/openapi.json").json()
    operations = schema["paths"]["/items/{entity_id}"]

    for method in ("get", "put", "delete"):
        responses = operations[method]["responses"]
        assert "404" in responses, method
        content = responses["404"]["content"]["application/json"]
        assert content["schema"]["$ref"].endswith("/ProblemDetail")
