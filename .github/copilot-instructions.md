# Copilot Instructions for TiebaContentReviewer

This repository implements a content review service for Tieba, processing data from a Redis Stream, evaluating it against configurable rules, and dispatching actions.

## Architecture Overview

The system follows a worker-based architecture:
- **Worker (`src/worker/consumer.py`)**: The core loop. Consumes messages from Redis Stream (`tieba:scraper:stream`), fetches active rules, and invokes the engine.
- **Engine (`src/core/engine.py`)**: Contains `RuleMatcher` which evaluates data against a set of `ReviewRule`s. Supports complex logic (AND, OR, NOT, XOR, etc.) and nested field access.
- **Infrastructure (`src/infra/`)**:
  - `dispatcher.py`: `ActionDispatcher` sends resulting actions to a Redis List (`tieba:actions:queue`).
  - `repository.py`: Manages rule persistence in PostgreSQL.
  - `db.py` & `redis_client.py`: Connection management.

**Data Flow**:
1. Scraper pushes data -> Redis Stream.
2. `ReviewWorker` reads stream group.
3. `RuleMatcher` evaluates data against loaded rules.
4. If matched, `ActionDispatcher` pushes actions -> Redis Stream.

## Developer Workflow

### Dependency Management
- Uses `uv` for dependency management (implied by tasks).
- `pyproject.toml` defines dependencies and tool configurations.

### Testing
- Run tests: `uv run pytest`
- Tests are located in `tests/` mirroring the `src/` structure.
- `pytest-asyncio` is configured in strict mode.

### Linting & Formatting
- **Ruff**: Used for formatting and linting. Run `uv run ruff format .` and `uv run ruff check .`.
- **MyPy**: Strict type checking is enabled. Run `uv run mypy src main.py`.
  - Configuration in `pyproject.toml`: `strict = true`, `disallow_untyped_defs = true`.

## Coding Conventions

- **Python Version**: Target Python 3.12+. Don't use deprecated features like `typing.Optional`, `typing.List`, etc.
- **Async/Await**: The codebase is fully asynchronous. Use `async def` and `await` for I/O operations (DB, Redis).
- **Type Hints**: MUST use type hints for all function arguments and return values.
  - Use `from __future__ import annotations` at the top of files.
  - Use `typing.TYPE_CHECKING` to avoid circular imports for type hints.
- **Configuration**: Access settings via `src.config.settings`. Do not hardcode constants.
- **Logging**: Use `tiebameow.utils.logger` instead of `print` or standard `logging`.

## Key Files & Directories

- `src/core/rules.py`: Definitions of `ReviewRule`, `RuleNode`, `Condition`.
- `src/core/engine.py`: Logic for rule evaluation.
- `src/worker/consumer.py`: Main worker implementation (`ReviewWorker`).
- `src/config.py`: Application configuration (Redis keys, DB creds).

## External Dependencies

- **Redis**: Critical for messaging (Streams, Lists, Pub/Sub).
- **PostgreSQL**: Stores persistent rules.
- **tiebameow**: Shared library for Tieba-related utilities and ORM.
