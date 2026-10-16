from typing import Any


def aggregate(cleaned: Any, rejected: Any) -> dict[str, Any]:
    from pyspark.sql import functions as F

    def totals() -> list[Any]:
        return [
            F.count("*").alias("gps_points"),
            F.sum("estimated_distance_km").alias("estimated_distance_km"),
            F.sum("estimated_active_seconds").alias("estimated_active_seconds"),
            F.sum(F.when(F.col("anomaly_reason").isNotNull(), 1).otherwise(0)).alias(
                "anomalous_segments"
            ),
        ]

    cleaned.createOrReplaceTempView("routeflow_cleaned_gps")
    daily = cleaned.sparkSession.sql("""
        select business_date, driver_id, count(*) as gps_points,
               sum(estimated_distance_km) as estimated_distance_km,
               sum(estimated_active_seconds) as estimated_active_seconds,
               sum(case when anomaly_reason is not null then 1 else 0 end) as anomalous_segments
        from routeflow_cleaned_gps group by business_date, driver_id
    """)
    daily = daily.withColumn(
        "estimated_average_speed_kmh",
        F.when(
            F.col("estimated_active_seconds") > 0,
            F.col("estimated_distance_km") / F.col("estimated_active_seconds") * 3600,
        ).otherwise(0.0),
    )
    hourly = cleaned.groupBy("business_date", "driver_id", "hour_utc").agg(*totals())
    zones = cleaned.groupBy("business_date", "zone_id", "hour_utc").agg(
        *totals(), F.countDistinct("driver_id").alias("observed_drivers")
    )
    quality = cleaned.groupBy("business_date", "driver_id").agg(
        F.count("*").alias("valid_points"),
        F.sum(F.when(F.col("metadata_missing"), 1).otherwise(0)).alias("missing_metadata_points"),
        F.sum(F.when(F.col("anomaly_reason").isNotNull(), 1).otherwise(0)).alias(
            "anomalous_segments"
        ),
    )
    invalid = rejected.withColumn(
        "business_date", F.coalesce(F.to_date("event_time"), F.to_date("ingested_at"))
    ).withColumn("driver_id", F.coalesce("driver_id", F.lit("UNKNOWN")))
    invalid_counts = invalid.groupBy("business_date", "driver_id").agg(
        F.count("*").alias("invalid_points")
    )
    quality = quality.join(invalid_counts, ["business_date", "driver_id"], "full").fillna(0)
    return {
        "driver_daily_distance": daily,
        "driver_hourly_activity": hourly,
        "zone_hourly_driver_activity": zones,
        "driver_gps_quality_metrics": quality,
        "rejected_driver_locations": invalid,
    }
