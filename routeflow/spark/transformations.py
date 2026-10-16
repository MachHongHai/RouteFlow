from typing import Any


def validate_points(points: Any) -> tuple[Any, Any]:
    from pyspark.sql import functions as F

    reason = (
        F.when(F.col("driver_id").isNull() | (F.length("driver_id") == 0), "MISSING_DRIVER")
        .when(F.col("event_id").isNull() | (F.length("event_id") == 0), "MISSING_EVENT_ID")
        .when(
            ~F.col("event_version").isin(1, 2) | F.col("event_version").isNull(),
            "UNSUPPORTED_SCHEMA",
        )
        .when(F.col("event_time").isNull() | F.col("ingested_at").isNull(), "INVALID_TIMESTAMP")
        .when(
            F.col("latitude").isNull()
            | F.col("longitude").isNull()
            | F.isnan("latitude")
            | F.isnan("longitude")
            | ~F.col("latitude").between(-90, 90)
            | ~F.col("longitude").between(-180, 180),
            "INVALID_COORDINATES",
        )
    )
    if "parse_error" in points.columns:
        reason = F.when(
            F.col("parse_error").isNotNull() | F.col("original_json").isNull(), "MALFORMED_EVENT"
        ).otherwise(reason)
    checked = points.withColumn("rejection_reason", reason)
    valid = checked.where(F.col("rejection_reason").isNull()).drop("rejection_reason")
    signature = F.to_json(
        F.struct("driver_id", "event_version", "latitude", "longitude", "event_time", "zone_id")
    )
    conflicts = valid.groupBy("event_id").agg(F.countDistinct(signature).alias("variants"))
    conflicts = conflicts.where("variants > 1").select("event_id")
    conflicting = valid.join(conflicts, "event_id", "inner").withColumn(
        "rejection_reason", F.lit("EVENT_ID_CONFLICT")
    )
    return (
        valid.join(conflicts, "event_id", "left_anti"),
        checked.where(F.col("rejection_reason").isNotNull()).unionByName(conflicting),
    )


def haversine(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> Any:
    from pyspark.sql import functions as F

    rad_lat1, rad_lat2 = F.radians(lat1), F.radians(lat2)
    a = F.pow(F.sin((rad_lat2 - rad_lat1) / 2), 2) + F.cos(rad_lat1) * F.cos(rad_lat2) * F.pow(
        F.sin((F.radians(lon2) - F.radians(lon1)) / 2), 2
    )
    return 6371.0088 * 2 * F.asin(F.sqrt(F.least(F.lit(1.0), F.greatest(F.lit(0.0), a))))


def segments(points: Any, drivers: Any, max_speed: float = 120, max_gap: int = 1800) -> Any:
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    dedup = Window.partitionBy("event_id").orderBy("ingested_at", "original_json")
    unique = points.withColumn("dedup_rank", F.row_number().over(dedup)).where("dedup_rank=1")
    window = Window.partitionBy("driver_id").orderBy("event_time", "event_id")
    ordered = (
        unique.withColumn("previous_latitude", F.lag("latitude").over(window))
        .withColumn("previous_longitude", F.lag("longitude").over(window))
        .withColumn("previous_time", F.lag("event_time").over(window))
    )
    calculated = ordered.withColumn(
        "segment_seconds", F.col("event_time").cast("long") - F.col("previous_time").cast("long")
    ).withColumn(
        "distance_km",
        F.when(
            F.col("previous_time").isNotNull(),
            haversine(
                F.col("previous_latitude"),
                F.col("previous_longitude"),
                F.col("latitude"),
                F.col("longitude"),
            ),
        ).otherwise(0.0),
    )
    calculated = calculated.withColumn(
        "speed_kmh",
        F.when(
            F.col("segment_seconds") > 0, F.col("distance_km") / F.col("segment_seconds") * 3600
        ).otherwise(0.0),
    )
    reason = (
        F.when(F.col("previous_time").isNull(), F.lit(None).cast("string"))
        .when(F.col("segment_seconds") > max_gap, "LARGE_GAP")
        .when((F.col("segment_seconds") == 0) & (F.col("distance_km") > 0), "ZERO_TIME_JUMP")
        .when(F.col("speed_kmh") > max_speed, "IMPOSSIBLE_SPEED")
        .when(F.col("distance_km") == 0, "IDENTICAL_COORDINATES")
    )
    calculated = calculated.withColumn("anomaly_reason", reason)
    accepted = F.col("anomaly_reason").isNull() & F.col("previous_time").isNotNull()
    calculated = calculated.withColumn(
        "estimated_distance_km", F.when(accepted, F.col("distance_km")).otherwise(0.0)
    ).withColumn(
        "estimated_active_seconds", F.when(accepted, F.col("segment_seconds")).otherwise(0)
    )
    # Small current profile reference is intentionally broadcast. Preserve GPS zone if supplied.
    enriched = calculated.join(F.broadcast(drivers), "driver_id", "left")
    return (
        enriched.withColumn("metadata_missing", F.col("driver_name").isNull())
        .withColumn("zone_id", F.coalesce("zone_id", "driver_zone_id", F.lit("UNKNOWN")))
        .withColumn("business_date", F.to_date("event_time"))
        .withColumn("hour_utc", F.hour("event_time"))
        .drop("driver_zone_id", "dedup_rank")
    )
