"""Async SQLAlchemy database connection manager."""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Self

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

from servicekit.logging import get_logger


def _install_sqlite_connect_pragmas(engine: AsyncEngine) -> None:
    """Install SQLite connection pragmas for performance and reliability."""

    def on_connect(dbapi_conn: sqlite3.Connection, _conn_record: ConnectionPoolEntry) -> None:
        """Configure SQLite pragmas on connection."""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA busy_timeout=30000;")  # 30s
        cur.execute("PRAGMA temp_store=MEMORY;")
        cur.execute("PRAGMA cache_size=-64000;")  # 64 MiB (negative => KiB)
        cur.execute("PRAGMA mmap_size=134217728;")  # 128 MiB
        cur.close()

    event.listen(engine.sync_engine, "connect", on_connect)


def get_alembic_dir() -> Path:
    """Return the path to the Alembic migration directory bundled with servicekit."""
    return Path(__file__).parent / "alembic"


class Database:
    """Generic async SQLAlchemy database connection manager."""

    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        alembic_dir: Path | None = None,
        auto_migrate: bool = True,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_recycle: int = 3600,
        pool_pre_ping: bool = True,
    ) -> None:
        """Initialize database with connection URL and pool configuration."""
        self.url = url
        self.alembic_dir = alembic_dir
        self.auto_migrate = auto_migrate

        # Build engine kwargs - skip pool params for in-memory SQLite databases
        engine_kwargs: dict = {"echo": echo, "future": True}
        if ":memory:" not in url:
            # Only add pool params for non-in-memory databases
            engine_kwargs.update(
                {
                    "pool_size": pool_size,
                    "max_overflow": max_overflow,
                    "pool_recycle": pool_recycle,
                    "pool_pre_ping": pool_pre_ping,
                }
            )

        self.engine: AsyncEngine = create_async_engine(url, **engine_kwargs)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )

    def _warn_if_default_migrations_lack_domain_tables(self) -> None:
        """Warn when bundled migrations run for an application that defines its own tables."""
        from servicekit.models import Base

        if not Base.metadata.tables:
            return

        logger = get_logger(__name__)
        logger.warning(
            "database.default_migrations_no_domain_tables",
            message=(
                "Running the migrations bundled with servicekit, which create only the alembic_version table. "
                "Application tables will not be created. Pass an application-specific alembic_dir to "
                "with_migrations(), or disable migrations with with_migrations(enabled=False) to create tables "
                "directly from the ORM metadata."
            ),
            table_count=len(Base.metadata.tables),
            alembic_dir=str(get_alembic_dir()),
        )

    async def init(self) -> None:
        """Initialize database tables using Alembic migrations or direct creation."""
        import asyncio

        # Import Base here to avoid circular import at module level
        from servicekit.models import Base

        # For databases without migrations, use direct table creation
        if not self.auto_migrate:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        else:
            # Use Alembic migrations
            alembic_cfg = Config()

            # Use custom alembic directory if provided, otherwise use bundled migrations
            script_location = self.alembic_dir if self.alembic_dir is not None else get_alembic_dir()
            if self.alembic_dir is None:
                self._warn_if_default_migrations_lack_domain_tables()
            alembic_cfg.set_main_option("script_location", str(script_location))

            alembic_cfg.set_main_option("sqlalchemy.url", self.url)

            # Run upgrade in executor to avoid event loop conflicts
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, command.upgrade, alembic_cfg, "head")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        """Create a database session context manager."""
        async with self._session_factory() as s:
            yield s

    async def dispose(self) -> None:
        """Dispose of database engine and connection pool."""
        await self.engine.dispose()


class SqliteDatabase(Database):
    """SQLite-specific database implementation with optimizations."""

    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        alembic_dir: Path | None = None,
        auto_migrate: bool = True,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_recycle: int = 3600,
        pool_pre_ping: bool = True,
    ) -> None:
        """Initialize SQLite database with connection URL and pool configuration."""
        self.url = url
        self.alembic_dir = alembic_dir
        self.auto_migrate = auto_migrate

        # Build engine kwargs - pool params only for non-in-memory databases
        engine_kwargs: dict = {"echo": echo, "future": True}
        if not self._is_in_memory_url(url):
            # File-based databases can use pool configuration
            engine_kwargs.update(
                {
                    "pool_size": pool_size,
                    "max_overflow": max_overflow,
                    "pool_recycle": pool_recycle,
                    "pool_pre_ping": pool_pre_ping,
                }
            )

        self.engine: AsyncEngine = create_async_engine(url, **engine_kwargs)
        _install_sqlite_connect_pragmas(self.engine)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )

    @staticmethod
    def _is_in_memory_url(url: str) -> bool:
        """Check if URL represents an in-memory database."""
        return ":memory:" in url

    def is_in_memory(self) -> bool:
        """Check if this is an in-memory database."""
        return self._is_in_memory_url(self.url)

    async def init(self) -> None:
        """Initialize database tables and configure SQLite using Alembic migrations."""
        # Import Base here to avoid circular import at module level
        from servicekit.models import Base

        # Set WAL mode first (if not in-memory)
        if not self.is_in_memory():
            async with self.engine.begin() as conn:
                await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")

        # For in-memory databases or when migrations are disabled, use direct table creation
        if self.is_in_memory() or not self.auto_migrate:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        else:
            # For file-based databases, use Alembic migrations
            await super().init()

    async def dispose(self) -> None:
        """Dispose database with WAL checkpoint for file-based databases."""
        if not self.is_in_memory():
            try:
                async with self.engine.begin() as conn:
                    await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass  # Don't fail dispose on checkpoint error
        await super().dispose()


class SqliteDatabaseBuilder:
    """Builder for SQLite database configuration with fluent API."""

    def __init__(self) -> None:
        """Initialize builder with default values."""
        self._url: str = ""
        self._echo: bool = False
        self._alembic_dir: Path | None = None
        self._auto_migrate: bool = True
        self._pool_size: int = 5
        self._max_overflow: int = 10
        self._pool_recycle: int = 3600
        self._pool_pre_ping: bool = True

    @classmethod
    def in_memory(cls) -> Self:
        """Create an in-memory SQLite database configuration."""
        builder = cls()
        builder._url = "sqlite+aiosqlite:///:memory:"
        return builder

    @classmethod
    def from_file(cls, path: str | Path) -> Self:
        """Create a file-based SQLite database configuration."""
        builder = cls()
        if isinstance(path, Path):
            path = str(path)
        builder._url = f"sqlite+aiosqlite:///{path}"
        return builder

    def with_echo(self, enabled: bool = True) -> Self:
        """Enable SQL query logging."""
        self._echo = enabled
        return self

    def with_migrations(self, enabled: bool = True, alembic_dir: Path | None = None) -> Self:
        """Configure migration behavior."""
        self._auto_migrate = enabled
        self._alembic_dir = alembic_dir
        return self

    def with_pool(
        self,
        size: int = 5,
        max_overflow: int = 10,
        recycle: int = 3600,
        pre_ping: bool = True,
    ) -> Self:
        """Configure connection pool settings."""
        self._pool_size = size
        self._max_overflow = max_overflow
        self._pool_recycle = recycle
        self._pool_pre_ping = pre_ping
        return self

    def build(self) -> SqliteDatabase:
        """Build and return configured SqliteDatabase instance."""
        if not self._url:
            raise ValueError("Database URL not configured. Use .in_memory() or .from_file()")

        return SqliteDatabase(
            url=self._url,
            echo=self._echo,
            alembic_dir=self._alembic_dir,
            auto_migrate=self._auto_migrate,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_recycle=self._pool_recycle,
            pool_pre_ping=self._pool_pre_ping,
        )
