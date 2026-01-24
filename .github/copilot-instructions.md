# Copilot Instructions for TiebaContentReviewer

This repository implements a high-performance content review service for Tieba, integrated with the [TiebaMeow](https://github.com/TiebaMeow/) ecosystem. It processes data from Redis Streams, evaluates it against dynamic rules, and dispatches results to downstream actions.

## Architecture & Data Flow

The system uses a **Worker-Engine-Dispatcher** pattern:
1.  **Ingestion (Worker)**: `ReviewWorker` (`src/worker/consumer.py`) consumes raw data chunks (Thread/Post/Comment) from a Redis Stream Consumer Group. It supports crash recovery via `_recovery_loop`.
2.  **Evaluation (Engine)**: `RuleMatcher` (`src/core/engine.py`) determines if data matches active `ReviewRule`s. It supports nested boolean logic (AND/OR/NOT/XOR) and deep field inspection.
3.  **Dispatch (Infrastructure)**: `ReviewResultDispatcher` (`src/infra/dispatcher.py`) serializes matches into `ReviewResultPayload` and pushes them to an **output Redis Stream** (not a list).

**Key Redis Keys (Configurable)**:
-   Input: `settings.REDIS_STREAM_KEY` (Default: `scraper:tieba:events`)
-   Output: `settings.REDIS_ACTION_STREAM_KEY`
-   Signaling: `settings.REDIS_RULES_CHANNEL` (Pub/Sub for hot-reloading rules)

## Developer Workflow

This project uses **uv** for all dependency and environment management.

-   **Install**: `uv sync`
-   **Test**: `uv run pytest` (Strict `pytest-asyncio` mode enabled)
-   **Lint/Format**: `uv run ruff check .` / `uv run ruff format .`
-   **Type Check**: `uv run mypy src main.py` (Strict mode enables `disallow_untyped_defs = true`, etc.)

## Coding Conventions

-   **Python 3.12+**: Use modern features. Avoid `typing.Optional/List/Dict`; use `|` unions and built-in generics (e.g., `list[str]`).
-   **Strict Typing**:
    -   Always import `from __future__ import annotations` at the top of files.
    -   Use `typing.TYPE_CHECKING` blocks to prevent circular imports.
    -   Every function **MUST** have type hints for arguments and return values.
-   **Asynchronous I/O**:
    -   All DB (PostgreSQL) and Redis interactions must be async (`await`).
    -   Use `asyncio.gather` for concurrency where appropriate.
-   **Logging**:
    -   **NEVER** use `print` or standard `logging`.
    -   **ALWAYS** use `tiebameow.utils.logger` (Loguru-style: `logger.info("Message {}", arg)`).
-   **Configuration**:
    -   Import settings via `from src.config import settings`.
    -   Do not hardcode Redis keys or DB credentials.

## Critical Files

-   `src/worker/consumer.py`: Main event loop (`xreadgroup`). Handles batching and stream recovery.
-   `src/core/engine.py`: Implements the `RuleMatcher` logic.
-   `src/infra/dispatcher.py`: Constructs `ReviewResultPayload` and executes `xadd`.
-   `src/core/rules.py`: `ReviewRule`, `RuleGroup`, `Condition` definitions (sourced from `tiebameow` schemas).

## Specific Patterns

-   **Rule Logic**: Rules are effectively syntax trees. `_evaluate_node` recursively checks `RuleGroup` logic.
-   **Message Ack**: Redis Stream messages must be acknowledged (`xack`) after successful processing (handled in `ReviewWorker._process_message`).
-   **Dependency Injection**: The worker receives its dependencies (`repository`, `dispatcher`, `matcher`, `redis_client`) in `__init__`, facilitating testing.
