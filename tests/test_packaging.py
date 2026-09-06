"""Tests that the built wheel is self-contained and usable outside the source checkout."""

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SMOKE_SCRIPT = """
import asyncio
import tempfile
from pathlib import Path

from servicekit import SqliteDatabaseBuilder, get_alembic_dir


async def main() -> None:
    assert get_alembic_dir().is_dir()
    with tempfile.TemporaryDirectory() as tmp_dir:
        database = SqliteDatabaseBuilder.from_file(Path(tmp_dir) / "smoke.db").build()
        await database.init()
        await database.dispose()
    print("OK")


asyncio.run(main())
"""


def _build_wheel(output_dir: Path) -> Path:
    """Build a wheel into the given directory and return its path."""
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(output_dir)],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    wheels = sorted(output_dir.glob("*.whl"))
    assert wheels, "uv build should produce a wheel"
    return wheels[-1]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not available on PATH")
def test_wheel_contains_bundled_migrations() -> None:
    """Test that the built wheel ships the Alembic migration environment."""
    with tempfile.TemporaryDirectory() as build_dir:
        wheel_path = _build_wheel(Path(build_dir))
        names = set(zipfile.ZipFile(wheel_path).namelist())

    assert "servicekit/alembic/env.py" in names
    assert "servicekit/alembic/script.py.mako" in names
    assert any(name.startswith("servicekit/alembic/versions/") and name.endswith(".py") for name in names)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not available on PATH")
def test_installed_wheel_initializes_file_database() -> None:
    """Test that a non-editable install can initialize a file database with bundled migrations."""
    with tempfile.TemporaryDirectory() as build_dir, tempfile.TemporaryDirectory() as run_dir:
        wheel_path = _build_wheel(Path(build_dir))
        result = subprocess.run(
            [
                "uv",
                "run",
                "--no-project",
                "--isolated",
                "--python",
                f"{sys.version_info.major}.{sys.version_info.minor}",
                "--with",
                str(wheel_path),
                "python",
                "-c",
                SMOKE_SCRIPT,
            ],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=600,
        )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "OK" in result.stdout
