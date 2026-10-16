from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    source_database_url: str = "postgresql+psycopg://routeflow:routeflow@127.0.0.1:55432/routeflow"
    warehouse_database_url: str = (
        "postgresql+psycopg://routeflow:routeflow@127.0.0.1:55433/warehouse"
    )
    google_cloud_project: str = "routeflow-local"
    topic: str = "delivery-events"
    subscription: str = "delivery-events-local"
    pubsub_emulator_host: str = "127.0.0.1:58085"
    warehouse_mode: str = "postgres"
    bigquery_dataset: str = "routeflow_raw"
    maximum_bytes_billed: int = 100_000_000
    archive_path: str = ".local/archive"
    archive_bucket: str = ""
    environment: str = "local"
    max_processing_attempts: int = 5
    api_key: str = ""
    data_lake_path: str = ".local/data_lake"
    spark_master: str = "local[2]"
    spark_lookback_days: int = 3
    gps_max_speed_kmh: float = 120.0
    gps_max_gap_seconds: int = 1800
    gcp_region: str = "us-central1"


@lru_cache
def settings() -> Settings:
    return Settings()
