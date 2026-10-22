# Development guide

Use Python 3.12 and the committed `uv.lock`. The console is buildless HTML/CSS/JavaScript;
Node.js is needed only for formatting and frontend development checks.

## Setup and checks

```bash
uv sync --frozen
npm ci --ignore-scripts
uv run ruff check .
uv run ruff format --check .
uv run mypy routeflow
uv run pytest
npm run check
docker compose --profile console config --quiet
```

Apply formatting with `uv run ruff format .` and `npm run format`. `.editorconfig`
defines encoding, newlines, and indentation. Follow the [testing guide](docs/TESTING.md)
for infrastructure-dependent suites; record actual outcomes in [validation](docs/VALIDATION.md).

On the maintainer's Windows workstation, run Python/Docker commands through
`scripts/dev.ps1` to keep cache/temp on D and enforce Docker storage on E.
For npm commands, set `npm_config_cache=D:\DevCache\npm` and TEMP/TMP on D.

## Source boundaries

- `domain.py` owns business transitions and transactional event creation.
- `relay.py`, `consumer.py`, and `storage.py` own delivery, validation, archive, and RAW writes.
- `operations.py` and `cli.py` coordinate jobs, replay/backfill, and reconciliation.
- `spark/` owns GPS validation, transformations, aggregation, and loading.
- `console.py` composes local HTTP routes; `console_database.py`, `console_generation.py`,
  `console_storage.py`, and `console_broker.py` isolate database access, batch tracking,
  storage policy, and fixed Docker operations.
- `dbt/` owns warehouse transformations and data tests. Preserve each model's documented grain.

Keep the core event path independent of console/frontend code. Contract changes belong in
the versioned JSON schemas with compatibility tests. Preserve at-least-once delivery semantics,
archive-before-ack behavior, business-key idempotency, and late-event handling.

The base Compose file must remain portable. Put machine-specific mounts in the Windows override;
keep the workstation guard active when using that override. Never commit runtime data, credentials,
database dumps, Terraform state, caches, or local build logs.

## Scope and evidence

Add meaningful tests for changed behavior. Run the relevant checks, then stop repeating successful
tests unless code changes or a failure warrants it. Keep README concise; place detailed procedures
in `docs/`. Local results do not prove cloud deployment, production capacity, or cost savings.
