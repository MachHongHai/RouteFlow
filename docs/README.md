# Documentation

Start with the [project README](../README.md) for the demo and
[local development](LOCAL_DEVELOPMENT.md) for complete commands.

## Architecture and data

- [Architecture](ARCHITECTURE.md): transaction, delivery, storage, and cloud boundaries.
- [Data model](DATA_MODEL.md): grains, dimensions, incremental facts, and SCD2.
- [Event contracts](EVENT_CONTRACTS.md): envelope versions and compatibility.
- [Spark architecture](SPARK_ARCHITECTURE.md) and [optimization](SPARK_OPTIMIZATION.md).
- [Analytical SQL](ANALYTICAL_QUERIES.sql): runnable business queries.
- [Architecture decisions](adr/): ten ADRs covering delivery, recovery, cloud, and Spark.

## Run and operate

- [Local development](LOCAL_DEVELOPMENT.md) and [console guide (Vietnamese)](LOCAL_CONSOLE_VI.md).
- [Operations](OPERATIONS.md), [recovery](FAILURE_RECOVERY.md), and [backfill](BACKFILL.md).
- [Testing](TESTING.md) and [validation evidence](VALIDATION.md).
- [Engineering report (Vietnamese)](ENGINEERING_REPORT.md): historical implementation report.

## Cloud and project scope

- [Current gaps (Vietnamese)](PROJECT_GAPS_VI.md).
- [First GCP setup (Vietnamese)](GCP_GETTING_STARTED_VI.md).
- [Deployment](CLOUD_DEPLOYMENT.md) and [cost assumptions](CLOUD_COSTS.md).
- [Portfolio notes](PORTFOLIO.md) and [interview guide](INTERVIEW_GUIDE.md).

## Maintainer workstation notes

These apply to the original Windows machine, not to the portable Compose setup:

- [D/E storage placement](DISK_STORAGE.md).
- [Docker Desktop recovery incident](DOCKER_RECOVERY_VI.md).

Historical run counts and incident timestamps remain evidence of those runs; they are not live
metrics. Screenshots show synthetic data from the local console.
