# Copilot Instructions for TiebaContentReviewer

This repository implements a scalable, rule-based content review service for Tieba, part of the `TiebaMeow` ecosystem. It evaluates content (Threads/Posts/Comments) against dynamic rules using local or remote logic.

## Architecture & Core Components

-   **Service Entry (`main.py`)**: Bootstraps the application, initializing DB, Redis, and the `WorkerManager`.
-   **Worker Management (`src/worker/manager.py`)**: Orchestrates multiple `ReviewWorker` instances dynamically based on active rules (keyed by `fid`).
-   **Event Processing (`src/worker/consumer.py`)**: Each `ReviewWorker` consumes from a Redis Stream Group, processing messages in batches with error recovery.
-   **Rule Engine (`src/core/engine.py`)**: Matches content against `ReviewRule` trees.
-   **Function Providers (`src/core/provider.py`)**: abstracted execution logic for rule conditions:
    -   `LocalFunctionProvider`: Executes Python functions registered in `src/core/registry.py`.
    -   `RpcFunctionProvider`: Calls a gRPC service (`src/rpc/review_service.proto`) for external logic.
    -   `HybridFunctionProvider`: Prefers local functions, falls back to RPC.

## Data Flow

1.  **Ingestion**: `ReviewWorker` pulls content events from `settings.REDIS_STREAM_KEY` (e.g., `scraper:tieba:events`).
2.  **Evaluation**:
    -   Content is converted to DTOs (`ThreadDTO`, `PostDTO`, `CommentDTO` from `tiebameow`).
    -   `RuleMatcher` evaluates active rules for the content's `fid`.
    -   Custom logic (`text_length`, `keyword_count`) is executed via the active `FunctionProvider`.
3.  **Result Dispatch**: Matches are serialized to `ReviewResultPayload` and pushed to `settings.REDIS_ACTION_STREAM_KEY`.

## Developer Workflow

This project uses **uv** for dependency management.

### Build & Run
-   **Install Dependencies**: `uv sync`
-   **Compile Protobuf**: Required if `src/rpc/review_service.proto` changes.
    ```bash
    uv run python -m grpc_tools.protoc -I=src/rpc --python_out=src/rpc --grpc_python_out=src/rpc src/rpc/review_service.proto
    ```
-   **Run locally**: `uv run python main.py`

### Testing & Quality
-   **Test**: `uv run pytest` (Strict `pytest-asyncio` mode).
-   **Lint/Format**: `uv run ruff check .` / `uv run ruff format .`
-   **Type Check**: `uv run mypy .` (Strict mode is active).

## Coding Conventions

-   **Typing**:
    -   Use `from __future__ import annotations`.
    -   Strict typing is enforced. Use `typing.TYPE_CHECKING` to avoid circular imports.
    -   Avoid `Optional`/`List`; use `| None` and `list[]`.
-   **Async I/O**: All I/O (Redis/DB/gRPC) must be `await`ed.
-   **External Models**: Use DTOs and Schemas (`ReviewRule`, `Condition`) from the `tiebameow` library, NOT defined locally.
-   **Logging**: Use `tiebameow.utils.logger` exclusively.
-   **Function Registry**: To add new local rule functions, decorate them with `@rule_functions.register()` in `src/functions.py`.

## Key Files

-   `src/rpc/review_service.proto`: gRPC definition for remote review logic.
-   `src/core/registry.py`: Registry for local rule functions.
-   `src/core/provider.py`: Strategy for executing rule functions (Local vs RPC).
-   `src/functions.py`: Implementation of common local review functions.
