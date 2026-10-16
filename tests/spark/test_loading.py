from datetime import date
from typing import Any

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def test_gps_to_parquet_to_warehouse_is_idempotent(
    isolated: None, spark: Any, tmp_path: Any
) -> None:
    from routeflow.db import engine
    from routeflow.spark.aggregation import aggregate
    from routeflow.spark.loader import load
    from routeflow.spark.transformations import segments, validate_points
    from tests.spark.test_transformations import SCHEMA, point, profiles

    points = spark.createDataFrame(
        [point("a", "2026-10-01T10:00:00", 0.0), point("b", "2026-10-01T10:02:00", 0.01)], SCHEMA
    )
    valid, rejected = validate_points(points)
    outputs = aggregate(segments(valid, profiles(spark)), rejected)
    run_path = str(tmp_path / "run")
    for name, frame in outputs.items():
        frame.write.mode("overwrite").partitionBy("business_date").parquet(
            f"{run_path}/gold/{name}"
        )
    day = date(2026, 10, 1)
    assert load(run_path, day, day) == 4
    assert load(run_path, day, day) == 4
    with engine(True).connect() as conn:
        row = conn.execute(text("select * from spark_driver_daily_distance")).mappings().one()
        assert row["gps_points"] == 2
        assert row["estimated_distance_km"] == pytest.approx(1.1119508, rel=1e-6)
