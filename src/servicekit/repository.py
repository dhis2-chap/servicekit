"""Base repository classes for data access layer."""

from abc import ABC, abstractmethod
from typing import Iterable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID


class Repository[T, IdT = ULID](ABC):
    """Abstract repository interface for data access operations."""

    @abstractmethod
    async def save(self, entity: T) -> T:
        """Save an entity to the database."""
        ...

    @abstractmethod
    async def save_all(self, entities: Iterable[T]) -> Sequence[T]:
        """Save multiple entities to the database."""
        ...

    @abstractmethod
    async def commit(self) -> None:
        """Commit the current database transaction."""
        ...

    @abstractmethod
    async def flush(self) -> None:
        """Flush pending changes to the database without committing."""
        ...

    @abstractmethod
    async def rollback(self) -> None:
        """Roll back the current database transaction."""
        ...

    @abstractmethod
    async def refresh_many(self, entities: Iterable[T]) -> None:
        """Refresh multiple entities from the database."""
        ...

    @abstractmethod
    async def delete(self, entity: T) -> None:
        """Delete an entity from the database."""
        ...

    @abstractmethod
    async def delete_by_id(self, id: IdT) -> None:
        """Delete an entity by its ID."""
        ...

    @abstractmethod
    async def delete_all(self) -> None:
        """Delete all entities from the database."""
        ...

    @abstractmethod
    async def delete_all_by_id(self, ids: Sequence[IdT]) -> None:
        """Delete multiple entities by their IDs."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Count the number of entities."""
        ...

    @abstractmethod
    async def exists_by_id(self, id: IdT) -> bool:
        """Check if an entity exists by its ID."""
        ...

    @abstractmethod
    async def find_all(self) -> Sequence[T]:
        """Find all entities ordered by ID."""
        ...

    @abstractmethod
    async def find_all_paginated(self, offset: int, limit: int) -> Sequence[T]:
        """Find entities with pagination, ordered by ID."""
        ...

    @abstractmethod
    async def find_all_by_id(self, ids: Sequence[IdT]) -> Sequence[T]:
        """Find entities by their IDs."""
        ...

    @abstractmethod
    async def find_by_id(self, id: IdT) -> T | None:
        """Find an entity by its ID."""
        ...


class BaseRepository[T, IdT = ULID](Repository[T, IdT]):
    """Base repository implementation with common CRUD operations."""

    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        """Initialize repository with database session and model type."""
        self.s = session
        self.model = model

    # ---------- Create ----------
    async def save(self, entity: T) -> T:
        """Save an entity to the database."""
        self.s.add(entity)
        return entity

    async def save_all(self, entities: Iterable[T]) -> Sequence[T]:
        """Save multiple entities to the database."""
        entity_list = list(entities)
        self.s.add_all(entity_list)
        return entity_list

    async def commit(self) -> None:
        """Commit the current database transaction."""
        await self.s.commit()

    async def flush(self) -> None:
        """Flush pending changes to the database without committing."""
        await self.s.flush()

    async def rollback(self) -> None:
        """Roll back the current database transaction."""
        await self.s.rollback()

    async def refresh_many(self, entities: Iterable[T]) -> None:
        """Refresh multiple entities from the database."""
        for e in entities:
            await self.s.refresh(e)

    # ---------- Delete ----------
    async def delete(self, entity: T) -> None:
        """Delete an entity from the database."""
        await self.s.delete(entity)

    async def delete_by_id(self, id: IdT) -> None:
        """Delete an entity by its ID."""
        id_col = getattr(self.model, "id")
        await self.s.execute(delete(self.model).where(id_col == id))

    async def delete_all(self) -> None:
        """Delete all entities from the database."""
        await self.s.execute(delete(self.model))

    async def delete_all_by_id(self, ids: Sequence[IdT]) -> None:
        """Delete multiple entities by their IDs."""
        if not ids:
            return
        # Access the "id" column generically
        id_col = getattr(self.model, "id")
        await self.s.execute(delete(self.model).where(id_col.in_(ids)))

    # ---------- Read / Count ----------
    async def count(self) -> int:
        """Count the number of entities."""
        return await self.s.scalar(select(func.count()).select_from(self.model)) or 0

    async def exists_by_id(self, id: IdT) -> bool:
        """Check if an entity exists by its ID."""
        # Access the "id" column generically
        id_col = getattr(self.model, "id")
        q = select(select(id_col).where(id_col == id).exists())
        return await self.s.scalar(q) or False

    async def find_all(self) -> Sequence[T]:
        """Find all entities ordered by ID."""
        id_col = getattr(self.model, "id")
        result = await self.s.scalars(select(self.model).order_by(id_col))
        return result.all()

    async def find_all_paginated(self, offset: int, limit: int) -> Sequence[T]:
        """Find entities with pagination, ordered by ID."""
        id_col = getattr(self.model, "id")
        result = await self.s.scalars(select(self.model).order_by(id_col).offset(offset).limit(limit))
        return result.all()

    async def find_all_by_id(self, ids: Sequence[IdT]) -> Sequence[T]:
        """Find entities by their IDs."""
        if not ids:
            return []
        id_col = getattr(self.model, "id")
        result = await self.s.scalars(select(self.model).where(id_col.in_(ids)))
        return result.all()

    async def find_by_id(self, id: IdT) -> T | None:
        """Find an entity by its ID."""
        return await self.s.get(self.model, id)

    async def get_stats(self) -> dict[str, int]:
        """Get collection statistics."""
        total = await self.count()
        return {"total": total}
