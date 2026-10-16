from typing import Any


def spark_session(master: str = "local[2]") -> Any:
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.appName("RouteFlow GPS historical analytics")
        .master(master)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.sql.files.maxRecordsPerFile", "250000")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
