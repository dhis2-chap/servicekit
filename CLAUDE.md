# CLAUDE.md

Guidance for Claude Code when working in this repository.

`servicekit` is an async SQLAlchemy + FastAPI framework: a reusable, domain-agnostic foundation for building data services (database, repository, manager, CRUD, auth, jobs, monitoring). Domain modules live in the separate [chapkit](https://github.com/dhis2-chap/chapkit) project.

For API/usage reference see the README and `docs/`; for working code see `examples/`. This file covers conventions not obvious from those.

## Non-negotiable rules

These are violated most often, so they come first:

1. **No AI attribution.** Never add "Co-Authored-By: Claude" or any AI attribution to commits, PRs, or code.
2. **No emojis anywhere.** Not in commit messages, PR descriptions, docstrings, comments, or code.
3. **Conventional commits, always.** Every commit message starts with a type prefix: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.

## Working agreement

- Be concise; follow existing style and patterns; prioritize readability.
- Type annotations required everywhere.
- Ask before creating branches or PRs.
- Always run `make format`, then `make lint` and `make test` after changes.

## Documentation

Every Python file, class, and function/method gets a one-line `"""docstring"""`.

## Git workflow

- Ask before creating a branch/PR. Branch from `main`, named by type: `feat/`, `fix/`, `refactor/`, `docs/`, `test/`, `chore/`.
- Commit messages: concise, conventional-commit prefix, no AI attribution (see non-negotiable rules).
- PRs must pass `make test` and `make lint`; coverage must not decrease.

## Architecture

- Core (`src/servicekit/*.py`) is framework-agnostic and **never imports from `api/`**.
- API layer (`src/servicekit/api/`) provides FastAPI integration and imports from core.

## Conventions

- **Full descriptive names, never abbreviations**: `self.repository` not `self.repo`, `config_repository` not `config_repo`. Applies to attributes, locals, parameters.
- **Repository methods**: `find_*` (entity or None), `find_all_*` (sequence), `exists_*` (bool), `count` (int).
- **Repository vs Manager**: repositories do low-level ORM access on Entity models; managers add Pydantic validation and business logic, working with In/Out schemas.
- **Routers**: extend `Router`, implement `_register_routes()`, expose via the `.create()` classmethod.
- **Endpoint paths**: operational monitoring at root (`/health`, `/metrics`); API versioned under `/api/v1/*`; computed/derived operations use a `$` prefix (e.g. `/api/v1/users/$schema`, `/services/$register`).
- **Code style**: Python 3.13+, line length 120, double quotes, async/await. Class member order: public → protected → private. `__all__` only in `__init__.py`.
- **Postman collections**: each example with REST endpoints includes one named exactly `postman_collection.json`.

## Database & migrations

- `SqliteDatabaseBuilder` for setup. File DBs auto-run Alembic migrations on init; in-memory DBs skip them (fast tests).
- Migrations ship inside the package at `src/servicekit/alembic/`; `get_alembic_dir()` returns that path. The bundled migration creates only the `alembic_version` table, so applications with their own tables pass `with_migrations(enabled=True, alembic_dir=...)` or `with_migrations(enabled=False)`.
- After changing ORM models: `make migrate MSG='description'`, review in `src/servicekit/alembic/versions/`, restart (auto-applies), commit the migration file. Apply manually with `make upgrade`.

## Dependencies

- Always use `uv`: `uv add <pkg>`, `uv add --dev <pkg>`, `uv lock --upgrade`, `uv sync`.
- Never hand-edit `pyproject.toml` dependencies. Never use `uv pip` in development (only acceptable in Dockerfiles for prebuilt wheels).
