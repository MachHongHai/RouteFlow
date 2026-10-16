from typing import Any


def read_archive(spark: Any, archive_path: str) -> Any:
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        DoubleType,
        IntegerType,
        StringType,
        StructField,
        StructType,
    )

    payload = StructType(
        [
            StructField("driver_id", StringType()),
            StructField("zone_id", StringType()),
            StructField("latitude", DoubleType()),
            StructField("longitude", DoubleType()),
        ]
    )
    envelope = StructType(
        [
            StructField("event_id", StringType()),
            StructField("event_type", StringType()),
            StructField("event_version", IntegerType()),
            StructField("event_time", StringType()),
            StructField("payload", payload),
            StructField("_corrupt_record", StringType()),
        ]
    )
    wrapper = StructType(
        [
            StructField("original_b64", StringType()),
            StructField("archived_at", StringType()),
            StructField("_corrupt_record", StringType()),
        ]
    )
    raw = spark.read.schema(wrapper).option("recursiveFileLookup", "true").json(archive_path)
    decoded = raw.withColumn("decoded", F.decode(F.unbase64("original_b64"), "UTF-8"))
    events = decoded.withColumn("event", F.from_json("decoded", envelope))
    return events.where(
        (F.col("event.event_type") == "DRIVER_LOCATION") | F.col("event.event_type").isNull()
    ).select(
        F.col("event.event_id").alias("event_id"),
        F.col("event.event_version").alias("event_version"),
        F.col("event.payload.driver_id").alias("driver_id"),
        F.col("event.payload.zone_id").alias("zone_id"),
        F.col("event.payload.latitude").alias("latitude"),
        F.col("event.payload.longitude").alias("longitude"),
        F.expr("try_to_timestamp(event.event_time)").alias("event_time"),
        F.expr("try_to_timestamp(archived_at)").alias("ingested_at"),
        F.col("decoded").alias("original_json"),
        F.col("event._corrupt_record").alias("parse_error"),
    )
