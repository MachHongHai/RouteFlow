FROM python:3.12-slim AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
RUN useradd --uid 10001 --create-home routeflow
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 DBT_PROFILES_DIR=/app/dbt

FROM dependencies AS spark-dependencies
COPY --from=eclipse-temurin:17-jre-jammy /opt/java/openjdk /opt/java/openjdk
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra spark --no-install-project
ENV JAVA_HOME=/opt/java/openjdk SPARK_HOME=/app/.venv/lib/python3.12/site-packages/pyspark PYSPARK_PYTHON=/app/.venv/bin/python PYSPARK_DRIVER_PYTHON=/app/.venv/bin/python PYTHONPATH=/app
ENV PATH="/opt/java/openjdk/bin:/app/.venv/lib/python3.12/site-packages/pyspark/bin:$PATH"

FROM dependencies AS runtime
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
RUN mkdir -p /app/dbt/target /app/dbt/logs && chown -R 10001 /app/dbt/target /app/dbt/logs
USER 10001
CMD ["uvicorn", "routeflow.api:app", "--host", "0.0.0.0", "--port", "8080"]

FROM spark-dependencies AS spark
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --extra spark
RUN mkdir -p /app/dbt/target /app/dbt/logs && chown -R 10001 /app/dbt/target /app/dbt/logs
USER 10001
CMD ["python", "-m", "routeflow.spark.job"]
