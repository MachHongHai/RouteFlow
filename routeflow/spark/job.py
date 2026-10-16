import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from routeflow.config import settings
from routeflow.db import engine, session
from routeflow.models import Driver, now, uid
from routeflow.operations import pipeline, validate_range
from routeflow.spark.aggregation import aggregate
from routeflow.spark.loader import load
from routeflow.spark.reader import read_archive
from routeflow.spark.session import spark_session
from routeflow.spark.transformations import segments, validate_points


def run(start: date, end: date, explain: bool = False, master: str | None = None) -> dict[str, Any]:
    validate_range(start, end)
    cfg = settings()
    spark = spark_session(master or cfg.spark_master)
    spark.sparkContext.setLogLevel("WARN")
    # Session advisory lock serializes GPS materializations without a distributed lock service.
    with engine().connect() as lock:
        if not lock.scalar(text("select pg_try_advisory_lock(80714001)")):
            raise RuntimeError("A GPS materialization is already running")
        try:
            with pipeline("spark_gps", "backfill") as metadata:
                started = time.monotonic()
                archive_path = (
                    f"gs://{cfg.archive_bucket}/events" if cfg.archive_bucket else cfg.archive_path
                )
                points = read_archive(spark, archive_path).cache()
                valid, rejected = validate_points(points)
                with session() as db:
                    profiles = [
                        (driver.id, driver.name, driver.zone_id)
                        for driver in db.scalars(select(Driver))
                    ]
                drivers = spark.createDataFrame(
                    profiles, "driver_id string, driver_name string, driver_zone_id string"
                )
                clean = segments(
                    valid, drivers, cfg.gps_max_speed_kmh, cfg.gps_max_gap_seconds
                ).cache()
                from pyspark.sql import functions as F

                latest = clean.agg(F.max("business_date")).first()[0]
                # A late point can change the next point on a much later date. Rebuild suffix.
                rejected_day = rejected.agg(
                    F.max(
                        F.coalesce(
                            F.to_date("event_time"), F.to_date("ingested_at"), F.current_date()
                        )
                    )
                ).first()[0]
                effective_end = max(end, latest or end, rejected_day or end)
                selected = clean.where(
                    F.col("business_date").between(str(start), str(effective_end))
                )
                rejected = rejected.where(
                    F.coalesce(F.to_date("event_time"), F.to_date("ingested_at")).between(
                        str(start), str(effective_end)
                    )
                )
                outputs = aggregate(selected, rejected)
                if explain:
                    selected.explain("formatted")
                metadata.records_read = points.count()
                metadata.records_rejected = rejected.count()
                clean_count = selected.count()
                totals = outputs["driver_daily_distance"].agg(F.sum("gps_points")).first()[0] or 0
                if (
                    totals != clean_count
                    or selected.select("event_id").distinct().count() != clean_count
                ):
                    raise ValueError("GPS aggregation or deduplication invariant failed")
                if selected.where("segment_seconds < 0 or estimated_distance_km < 0").count():
                    raise ValueError("GPS negative duration/distance invariant failed")
                run_path = cfg.data_lake_path.rstrip("/") + "/runs/" + uid()
                selected.repartition(2, "business_date").write.mode("overwrite").partitionBy(
                    "business_date"
                ).parquet(run_path + "/silver/cleaned_driver_locations")
                for name, frame in outputs.items():
                    frame.coalesce(1).write.mode("overwrite").partitionBy("business_date").parquet(
                        f"{run_path}/gold/{name}"
                    )
                metadata.records_written = load(run_path, start, effective_end)
                result = {
                    "run_id": metadata.id,
                    "start": str(start),
                    "end": str(effective_end),
                    "input_points": metadata.records_read,
                    "valid_points": clean_count,
                    "rejected_points": metadata.records_rejected,
                    "warehouse_rows": metadata.records_written,
                    "run_path": run_path,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
                # Immutable run outputs + a manifest identify accepted generations. Warehouse is
                # authoritative; retry atomically replaces the same suffix even after a crash.
                if not run_path.startswith("gs://"):
                    manifest = Path(cfg.data_lake_path) / "latest_run.json"
                    temporary = manifest.with_suffix(".tmp")
                    temporary.write_text(json.dumps(result, indent=2))
                    temporary.replace(manifest)
                else:
                    from google.cloud import storage  # type: ignore[attr-defined]

                    bucket, prefix = cfg.data_lake_path[5:].split("/", 1)
                    storage.Client().bucket(bucket).blob(
                        prefix + "/latest_run.json"
                    ).upload_from_string(json.dumps(result), content_type="application/json")
                clean.unpersist()
                points.unpersist()
                return result
        finally:
            lock.execute(text("select pg_advisory_unlock(80714001)"))
            spark.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process archived RouteFlow GPS into Parquet and DWH"
    )
    parser.add_argument("--from", dest="start", type=date.fromisoformat)
    parser.add_argument("--to", dest="end", type=date.fromisoformat)
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args()
    end = args.end or now().date()
    start = args.start or end - timedelta(days=settings().spark_lookback_days - 1)
    print(json.dumps(run(start, end, args.explain)))


if __name__ == "__main__":
    main()
