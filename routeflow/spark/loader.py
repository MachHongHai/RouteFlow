from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Date, Float, Integer, MetaData, String, Table, delete

from routeflow.config import settings
from routeflow.db import engine

DATASETS: dict[str, dict[str, Any]] = {
    "driver_daily_distance": {
        "driver_id": String,
        "gps_points": Integer,
        "estimated_distance_km": Float,
        "estimated_active_seconds": Integer,
        "anomalous_segments": Integer,
        "estimated_average_speed_kmh": Float,
    },
    "driver_hourly_activity": {
        "driver_id": String,
        "hour_utc": Integer,
        "gps_points": Integer,
        "estimated_distance_km": Float,
        "estimated_active_seconds": Integer,
        "anomalous_segments": Integer,
    },
    "zone_hourly_driver_activity": {
        "zone_id": String,
        "hour_utc": Integer,
        "gps_points": Integer,
        "estimated_distance_km": Float,
        "estimated_active_seconds": Integer,
        "anomalous_segments": Integer,
        "observed_drivers": Integer,
    },
    "driver_gps_quality_metrics": {
        "driver_id": String,
        "valid_points": Integer,
        "missing_metadata_points": Integer,
        "anomalous_segments": Integer,
        "invalid_points": Integer,
    },
}


def tables() -> dict[str, Table]:
    metadata = MetaData()
    return {
        name: Table(
            "spark_" + name,
            metadata,
            Column("business_date", Date, nullable=False),
            *(Column(field, data_type) for field, data_type in columns.items()),
        )
        for name, columns in DATASETS.items()
    }


def initialize() -> None:
    if settings().warehouse_mode == "postgres":
        for table in tables().values():
            table.create(engine(True), checkfirst=True)


def load(run_path: str, start: date, end: date) -> int:
    if run_path.startswith("gs://"):
        return load_bigquery(run_path, start, end)
    import pyarrow.dataset as ds

    count = 0
    initialize()
    # All four dataset replacements are one warehouse transaction; failures roll back together.
    with engine(True).begin() as connection:
        for name, table in tables().items():
            connection.execute(delete(table).where(table.c.business_date.between(start, end)))
            path = Path(run_path) / "gold" / name
            if not list(path.rglob("*.parquet")):
                continue
            dataset = ds.dataset(
                path, format="parquet", partitioning="hive", exclude_invalid_files=True
            )
            for batch in dataset.to_batches(batch_size=1000):
                rows = batch.to_pylist()
                for row in rows:
                    row["business_date"] = date.fromisoformat(str(row["business_date"]))
                connection.execute(table.insert(), rows)
                count += len(rows)
    return count


def load_bigquery(run_path: str, start: date, end: date) -> int:
    import google.cloud.storage as storage
    from google.cloud import bigquery

    cfg = settings()
    client = bigquery.Client(project=cfg.google_cloud_project)
    suffix = run_path.rstrip("/").split("/")[-1].replace("-", "")
    replacements = []
    stages = []
    bucket_name, object_prefix = run_path[5:].split("/", 1)
    storage_client = storage.Client(project=cfg.google_cloud_project)
    for name in DATASETS:
        destination = f"{cfg.google_cloud_project}.{cfg.bigquery_dataset}.spark_{name}"
        replacements.append(
            f"delete from `{destination}` where business_date between @start and @end;"
        )
        objects = storage_client.list_blobs(bucket_name, prefix=f"{object_prefix}/gold/{name}/")
        if not any(blob.name.endswith(".parquet") for blob in objects):
            continue
        stage = f"{cfg.google_cloud_project}.{cfg.bigquery_dataset}.stage_{name}_{suffix}"
        prefix = f"{run_path}/gold/{name}"
        hive = bigquery.HivePartitioningOptions()
        hive.mode = "AUTO"
        hive.source_uri_prefix = prefix
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition="WRITE_TRUNCATE",
            hive_partitioning_options=hive,
        )
        client.load_table_from_uri(
            f"{prefix}/*/*.parquet", stage, job_config=config, location=cfg.gcp_region
        ).result()
        stages.append(stage)
        replacements.append(f"insert into `{destination}` select * from `{stage}`;")
    query_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=cfg.maximum_bytes_billed,
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ],
    )
    job = client.query(
        "begin transaction;\n" + "\n".join(replacements) + "\ncommit transaction;",
        job_config=query_config,
    )
    job.result()
    for stage in stages:
        client.delete_table(stage, not_found_ok=True)
    return int(job.num_dml_affected_rows or 0)
