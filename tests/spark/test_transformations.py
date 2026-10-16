from datetime import UTC, datetime
from typing import Any

import pytest

from routeflow.spark.aggregation import aggregate
from routeflow.spark.transformations import segments, validate_points

SCHEMA = (
    "event_id string, driver_id string, event_version int, latitude double, "
    "longitude double, event_time timestamp, ingested_at timestamp, "
    "zone_id string, original_json string"
)


def point(
    identifier: str,
    at: str,
    longitude: float,
    latitude: float = 0.0,
    driver: str | None = "driver-1",
) -> tuple[Any, ...]:
    timestamp = datetime.fromisoformat(at).replace(tzinfo=UTC)
    return identifier, driver, 1, latitude, longitude, timestamp, timestamp, "zone-1", identifier


def profiles(spark: Any) -> Any:
    return spark.createDataFrame(
        [("driver-1", "Driver One", "zone-1")],
        "driver_id string, driver_name string, driver_zone_id string",
    )


def test_haversine_order_dedup_and_summary(spark: Any) -> None:
    first = point("a", "2026-10-01T10:00:00", 0.0)
    second = point("b", "2026-10-01T10:02:00", 0.01)
    points = spark.createDataFrame([second, first, first], SCHEMA)
    valid, rejected = validate_points(points)
    cleaned = segments(valid, profiles(spark))
    rows = cleaned.orderBy("event_time").collect()
    assert len(rows) == 2
    assert rows[0].distance_km == 0
    assert rows[1].estimated_distance_km == pytest.approx(1.1119508, rel=1e-6)
    assert rows[1].segment_seconds == 120
    daily = aggregate(cleaned, rejected)["driver_daily_distance"].first()
    assert daily.gps_points == 2
    assert daily.estimated_average_speed_kmh == pytest.approx(33.35852, rel=1e-5)


def test_invalid_missing_and_anomalies(spark: Any) -> None:
    points = spark.createDataFrame(
        [
            point("a", "2026-10-01T10:00:00", 0.0),
            point("b", "2026-10-01T10:00:10", 30.0),
            point("c", "2026-10-01T12:00:00", 30.01),
            point("d", "2026-10-01T12:00:10", 30.01),
            point("invalid", "2026-10-01T12:00:11", 0.0, 91.0),
            point("missing", "2026-10-01T12:00:12", 0.0, driver=None),
            point("unknown", "2026-10-01T12:00:13", 0.0, driver="unknown"),
        ],
        SCHEMA,
    )
    valid, rejected = validate_points(points)
    assert rejected.count() == 2
    rows = {row.event_id: row for row in segments(valid, profiles(spark)).collect()}
    assert rows["b"].anomaly_reason == "IMPOSSIBLE_SPEED"
    assert rows["c"].anomaly_reason == "LARGE_GAP"
    assert rows["d"].anomaly_reason == "IDENTICAL_COORDINATES"
    assert rows["b"].estimated_distance_km == 0
    assert rows["unknown"].metadata_missing


def test_late_point_across_midnight_recomputes_next_day(spark: Any) -> None:
    original = [point("a", "2026-10-01T23:59:00", 0.0), point("c", "2026-10-02T00:01:00", 0.02)]
    initial = segments(spark.createDataFrame(original, SCHEMA), profiles(spark))
    distance_before = initial.where("business_date='2026-10-02'").first().estimated_distance_km
    late = point("b", "2026-10-01T23:59:30", 0.005)
    recomputed = segments(spark.createDataFrame(original + [late], SCHEMA), profiles(spark))
    distance_after = recomputed.where("business_date='2026-10-02'").first().estimated_distance_km
    assert distance_before == pytest.approx(2.2239016, rel=1e-6)
    assert distance_after == pytest.approx(1.6679262, rel=1e-6)


def test_zero_time_jump_is_not_counted(spark: Any) -> None:
    points = spark.createDataFrame(
        [point("a", "2026-10-01T10:00:00", 0.0), point("b", "2026-10-01T10:00:00", 1.0)], SCHEMA
    )
    rows = {row.event_id: row for row in segments(points, profiles(spark)).collect()}
    assert rows["b"].anomaly_reason == "ZERO_TIME_JUMP"
    assert rows["b"].estimated_distance_km == 0


def test_partitioned_parquet_round_trip(spark: Any, tmp_path: Any) -> None:
    points = spark.createDataFrame(
        [point("a", "2026-10-01T23:59:00", 0.0), point("b", "2026-10-02T00:01:00", 0.01)], SCHEMA
    )
    clean = segments(points, profiles(spark))
    path = str(tmp_path / "silver")
    clean.write.mode("overwrite").partitionBy("business_date").parquet(path)
    loaded = spark.read.parquet(path)
    assert loaded.count() == 2
    assert loaded.select("business_date").distinct().count() == 2
    assert loaded.where("business_date='2026-10-02'").first().segment_seconds == 120


def test_conflicting_event_identifiers_are_rejected(spark: Any) -> None:
    points = spark.createDataFrame(
        [point("a", "2026-10-01T10:00:00", 0.0), point("a", "2026-10-01T10:00:00", 1.0)], SCHEMA
    )
    valid, rejected = validate_points(points)
    assert valid.count() == 0
    assert rejected.count() == 2
    assert {row.rejection_reason for row in rejected.collect()} == {"EVENT_ID_CONFLICT"}


@pytest.mark.parametrize(
    "field,value,reason", [(2, 99, "UNSUPPORTED_SCHEMA"), (5, None, "INVALID_TIMESTAMP")]
)
def test_schema_and_timestamp_rejections(spark: Any, field: int, value: Any, reason: str) -> None:
    row = list(point("a", "2026-10-01T10:00:00", 0.0))
    row[field] = value
    valid, rejected = validate_points(spark.createDataFrame([tuple(row)], SCHEMA))
    assert valid.count() == 0
    assert rejected.first().rejection_reason == reason


def test_reader_preserves_poison_records(
    spark: Any, tmp_path: Any, monkeypatch: Any, event: dict[str, Any]
) -> None:
    import json

    from routeflow.config import settings
    from routeflow.spark.reader import read_archive
    from routeflow.storage import Archive

    monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path))
    settings.cache_clear()
    archive = Archive()
    archive.write(json.dumps(event).encode())
    event["event_version"] = 99
    archive.write(json.dumps(event).encode())
    archive.write(b"not json")
    valid, rejected = validate_points(read_archive(spark, str(tmp_path)))
    assert valid.count() == 1
    assert rejected.count() == 2
    assert rejected.where("original_json is null").count() == 0
    settings.cache_clear()
