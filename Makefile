.PHONY: install up down seed generate wait dbt reconcile metrics test lint spark-up spark-test pipeline
install:
	uv sync --frozen
up:
	docker compose up -d --build
down:
	docker compose --profile spark down
seed:
	docker compose exec -T api python -m routeflow.cli seed
generate:
	docker compose exec -T api python -m routeflow.generator --orders 20 --seed 42
wait:
	docker compose exec -T api python -m routeflow.cli wait-ingestion
dbt:
	docker compose exec -T api python -m routeflow.cli dbt
reconcile:
	docker compose exec -T api python -m routeflow.cli reconcile --grace-seconds 0
metrics:
	docker compose exec -T api python -m routeflow.cli metrics
test:
	uv run pytest
lint:
	uv run ruff check .
	uv run mypy routeflow
spark-up:
	docker compose --profile spark up -d --build spark-master spark-worker
spark-test:
	docker compose --profile spark run --rm --no-deps -e RUN_INTEGRATION=1 --entrypoint python spark-job -m pytest tests/spark -q -o cache_dir=/tmp/pytest-cache
pipeline:
	uv run python scripts/local_pipeline.py --orders 20 --spark
