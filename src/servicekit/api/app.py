"""App system for hosting static web applications."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from servicekit.logging import get_logger

logger = get_logger(__name__)


class AppManifest(BaseModel):
    """App manifest configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Human-readable app name")
    version: str = Field(description="Semantic version")
    prefix: str = Field(description="URL prefix for mounting")
    description: str | None = Field(default=None, description="App description")
    author: str | None = Field(default=None, description="Author name")
    entry: str = Field(default="index.html", description="Entry point filename")

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        """Validate mount prefix format."""
        if not v.startswith("/"):
            raise ValueError("prefix must start with '/'")
        if ".." in v:
            raise ValueError("prefix cannot contain '..'")
        if v.startswith("/api/") or v == "/api":
            raise ValueError("prefix cannot be '/api' or start with '/api/'")
        return v

    @field_validator("entry")
    @classmethod
    def validate_entry(cls, v: str) -> str:
        """Validate entry file path for security."""
        if ".." in v:
            raise ValueError("entry cannot contain '..'")
        if v.startswith("/"):
            raise ValueError("entry must be a relative path")
        # Normalize and check for path traversal
        normalized = Path(v).as_posix()
        if normalized.startswith("../") or "/../" in normalized:
            raise ValueError("entry cannot contain path traversal")
        return v


@dataclass
class App:
    """Represents a loaded app with manifest and directory."""

    manifest: AppManifest
    directory: Path
    prefix: str  # May differ from manifest if overridden
    is_package: bool  # True if loaded from package resources


class EntryStaticFiles(StaticFiles):
    """Static file server that serves an app's configured entry file at the mount root."""

    def __init__(self, *args: Any, entry: str = "index.html", **kwargs: Any) -> None:
        """Initialize static files with the entry filename served for the mount root."""
        super().__init__(*args, **kwargs)
        self.entry = entry

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Serve the configured entry file for the mount root, other paths unchanged."""
        if path in ("", "."):
            return await super().get_response(self.entry, scope)
        return await super().get_response(path, scope)


class AppLoader:
    """Loads and validates apps from filesystem or package resources."""

    @staticmethod
    def load(path: str | Path | tuple[str, str], prefix: str | None = None) -> App:
        """Load and validate app from filesystem path or package resource tuple."""
        # Detect source type and resolve to directory
        if isinstance(path, tuple):
            # Package resource
            dir_path, is_package = AppLoader._resolve_package_path(path)
        else:
            # Filesystem path
            dir_path = Path(path).resolve()
            is_package = False

            if not dir_path.exists():
                raise FileNotFoundError(f"App directory not found: {dir_path}")
            if not dir_path.is_dir():
                raise NotADirectoryError(f"App path is not a directory: {dir_path}")

        # Load and validate manifest
        manifest_path = dir_path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest.json not found in: {dir_path}")

        try:
            with manifest_path.open() as f:
                manifest_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in manifest.json: {e}") from e

        manifest = AppManifest(**manifest_data)

        # Validate entry file exists
        entry_path = dir_path / manifest.entry
        if not entry_path.exists():
            raise FileNotFoundError(f"Entry file '{manifest.entry}' not found in: {dir_path}")

        # Use override or manifest prefix
        final_prefix = prefix if prefix is not None else manifest.prefix

        # Re-validate prefix if overridden
        if prefix is not None:
            validated = AppManifest(
                name=manifest.name,
                version=manifest.version,
                prefix=final_prefix,
            )
            final_prefix = validated.prefix

        return App(
            manifest=manifest,
            directory=dir_path,
            prefix=final_prefix,
            is_package=is_package,
        )

    @staticmethod
    def discover(path: str | Path | tuple[str, str]) -> list[App]:
        """Discover all apps with manifest.json in directory."""
        # Resolve directory
        if isinstance(path, tuple):
            dir_path, _ = AppLoader._resolve_package_path(path)
        else:
            dir_path = Path(path).resolve()

            if not dir_path.exists():
                raise FileNotFoundError(f"Apps directory not found: {dir_path}")
            if not dir_path.is_dir():
                raise NotADirectoryError(f"Apps path is not a directory: {dir_path}")

        # Scan for subdirectories with manifest.json
        apps: list[App] = []
        for subdir in dir_path.iterdir():
            if subdir.is_dir() and (subdir / "manifest.json").exists():
                try:
                    # Determine if we're in a package context
                    if isinstance(path, tuple):
                        # Build tuple path for subdirectory
                        package_name: str = path[0]
                        base_path: str = path[1]
                        subdir_name = subdir.name
                        subpath = f"{base_path}/{subdir_name}" if base_path else subdir_name
                        app = AppLoader.load((package_name, subpath))
                    else:
                        app = AppLoader.load(subdir)
                    apps.append(app)
                except Exception as e:
                    # Log but don't fail discovery for invalid apps
                    logger.warning(
                        "app.discovery.failed",
                        directory=str(subdir),
                        error=str(e),
                    )

        return apps

    @staticmethod
    def _resolve_package_path(package_tuple: tuple[str, str]) -> tuple[Path, bool]:
        """Resolve package resource tuple to filesystem path."""
        package_name, subpath = package_tuple

        # Validate subpath for security
        if ".." in subpath:
            raise ValueError(f"subpath cannot contain '..' (got: {subpath})")
        if subpath.startswith("/"):
            raise ValueError(f"subpath must be relative (got: {subpath})")

        try:
            spec = importlib.util.find_spec(package_name)
        except (ModuleNotFoundError, ValueError) as e:
            raise ValueError(f"Package '{package_name}' could not be found") from e

        if spec is None or spec.origin is None:
            raise ValueError(f"Package '{package_name}' could not be found")

        # Resolve to package directory
        package_dir = Path(spec.origin).parent
        app_dir = package_dir / subpath

        # Verify resolved path is still within package directory
        try:
            app_dir.resolve().relative_to(package_dir.resolve())
        except ValueError as e:
            raise ValueError(f"App path '{subpath}' escapes package directory") from e

        if not app_dir.exists():
            raise FileNotFoundError(f"App path '{subpath}' not found in package '{package_name}'")
        if not app_dir.is_dir():
            raise NotADirectoryError(f"App path '{subpath}' in package '{package_name}' is not a directory")

        return app_dir, True


class AppInfo(BaseModel):
    """App metadata for API responses."""

    name: str = Field(description="Human-readable app name")
    version: str = Field(description="Semantic version")
    prefix: str = Field(description="URL prefix for mounting")
    description: str | None = Field(default=None, description="App description")
    author: str | None = Field(default=None, description="Author name")
    entry: str = Field(description="Entry point filename")
    is_package: bool = Field(description="Whether app is loaded from package resources")


class AppManager:
    """Lightweight manager for app metadata queries."""

    def __init__(self, apps: list[App]):
        """Initialize with loaded apps."""
        self._apps = apps

    def list(self) -> list[App]:
        """Return all installed apps."""
        return self._apps

    def get(self, prefix: str) -> App | None:
        """Get app by mount prefix."""
        return next((app for app in self._apps if app.prefix == prefix), None)
