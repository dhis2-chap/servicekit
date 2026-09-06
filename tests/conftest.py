"""Test configuration and shared fixtures."""

from pydantic import BaseModel
from sqlalchemy import PickleType
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from servicekit.manager import BaseManager
from servicekit.models import Entity
from servicekit.repository import BaseRepository
from servicekit.schemas import EntityIn, EntityOut


class DemoData(BaseModel):
    """Simple data schema for testing."""

    x: int
    y: int
    z: int
    tags: list[str]


class _FixtureEntity(Entity):
    """Generic test entity for repository/manager tests."""

    __test__ = False  # Tell pytest not to collect this class
    __tablename__ = "test_entities"

    name: Mapped[str] = mapped_column(nullable=False)
    data: Mapped[dict] = mapped_column(PickleType(protocol=4), nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True, default=None)


class _FixtureEntityIn(EntityIn):
    """Input schema for test entity."""

    __test__ = False  # Tell pytest not to collect this class
    name: str
    data: DemoData
    description: str | None = None


class _FixtureEntityOut(EntityOut):
    """Output schema for test entity."""

    __test__ = False  # Tell pytest not to collect this class
    name: str
    data: DemoData
    description: str | None = None


class _FixtureEntityRepository(BaseRepository[_FixtureEntity, ULID]):
    """Repository for test entities."""

    __test__ = False  # Tell pytest not to collect this class

    def __init__(self, session: AsyncSession) -> None:
        """Initialize test entity repository."""
        super().__init__(session, _FixtureEntity)


class _FixtureEntityManager(BaseManager[_FixtureEntity, _FixtureEntityIn, _FixtureEntityOut, ULID]):
    """Manager for test entities."""

    __test__ = False  # Tell pytest not to collect this class

    def __init__(self, repository: _FixtureEntityRepository):
        """Initialize test entity manager."""
        super().__init__(repository, _FixtureEntity, _FixtureEntityOut)


# Expose without leading underscore for easier test imports
TestEntity = _FixtureEntity
TestEntityIn = _FixtureEntityIn
TestEntityOut = _FixtureEntityOut
TestEntityRepository = _FixtureEntityRepository
TestEntityManager = _FixtureEntityManager
