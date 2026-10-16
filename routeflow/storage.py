import hashlib
import io
import json
import os
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    select,
)
from sqlalchemy.dialects.postgresql import insert

from routeflow.config import settings
from routeflow.db import engine
from routeflow.models import now, uid

metadata = MetaData()
raw_events = Table(
    "raw_events",
    metadata,
    Column("event_id", String(36), primary_key=True),
    Column("event_type", String(40), nullable=False),
    Column("event_version", Integer, nullable=False),
    Column("aggregate_id", String(36), nullable=False, index=True),
    Column("aggregate_version", Integer, nullable=False),
    Column("event_time", DateTime(timezone=True), nullable=False),
    Column("produced_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False, index=True),
    Column("processed_at", DateTime(timezone=True), nullable=False),
    Column("payload", Text, nullable=False),
    Column("event_json", Text, nullable=False),
    Column("fingerprint", String(64), nullable=False),
)
delivery_attempts = Table(
    "raw_delivery_attempts",
    metadata,
    Column("attempt_id", String(36), primary_key=True),
    Column("event_id", String(36), nullable=False, index=True),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
)


def canonical(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


class EventCollision(ValueError):
    """A producer reused an identifier for different content."""


class Archive:
    def __init__(self) -> None:
        self.cfg = settings()

    def write(self, data: bytes) -> str:
        # Partition by archive receipt time, even for malformed or very late inputs.
        digest = hashlib.sha256(data).hexdigest()
        key = now().strftime("events/year=%Y/month=%m/day=%d/hour=%H/") + digest + ".jsonl"
        wrapper = (
            json.dumps(
                {
                    "original_b64": __import__("base64").b64encode(data).decode(),
                    "archived_at": now().isoformat(),
                }
            )
            + "\n"
        )
        if self.cfg.archive_bucket:
            from google.api_core.exceptions import PreconditionFailed
            from google.cloud import storage  # type: ignore[attr-defined]

            blob = storage.Client().bucket(self.cfg.archive_bucket).blob(key)
            try:
                blob.upload_from_string(
                    wrapper, content_type="application/x-ndjson", if_generation_match=0
                )
            except PreconditionFailed:
                pass  # Existing immutable object contains the same SHA-256 input.
        else:
            path = Path(self.cfg.archive_path) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
                    temporary = Path(tmp.name)
                    tmp.write(wrapper.encode())
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(temporary, path)
        return key

    def read(self) -> Iterator[bytes]:
        import base64

        if self.cfg.archive_bucket:
            from google.cloud import storage  # type: ignore[attr-defined]

            for blob in storage.Client().list_blobs(self.cfg.archive_bucket, prefix="events/"):
                for line in blob.download_as_text().splitlines():
                    yield base64.b64decode(json.loads(line)["original_b64"])
        else:
            for path in sorted(Path(self.cfg.archive_path).rglob("*.jsonl")):
                for line in path.read_text().splitlines():
                    yield base64.b64decode(json.loads(line)["original_b64"])


def raw_row(event: dict[str, Any]) -> dict[str, Any]:
    body = canonical(event)
    row = {
        key: event[key]
        for key in (
            "event_id",
            "event_type",
            "event_version",
            "aggregate_id",
            "aggregate_version",
            "event_time",
            "produced_at",
        )
    }
    row.update(
        ingested_at=now(),
        processed_at=now(),
        payload=canonical(event["payload"]),
        event_json=body,
        fingerprint=hashlib.sha256(body.encode()).hexdigest(),
    )
    for key in ("event_time", "produced_at"):
        row[key] = datetime.fromisoformat(row[key].replace("Z", "+00:00"))
    return row


class Warehouse:
    def init(self) -> None:
        if settings().warehouse_mode == "postgres":
            metadata.create_all(engine(True))
            from routeflow.spark.loader import initialize

            initialize()
        # BigQuery datasets and schema are managed by Terraform.

    def write(self, event: dict[str, Any]) -> bool:
        row = raw_row(event)
        if settings().warehouse_mode == "bigquery":
            return self._bigquery_write(row)
        with engine(True).begin() as conn:
            conn.execute(
                insert(delivery_attempts).values(
                    attempt_id=uid(), event_id=event["event_id"], ingested_at=now()
                )
            )
            inserted = conn.execute(
                insert(raw_events)
                .values(**row)
                .on_conflict_do_nothing()
                .returning(raw_events.c.event_id)
            ).scalar_one_or_none()
            existing = conn.execute(
                select(raw_events.c.fingerprint).where(raw_events.c.event_id == row["event_id"])
            ).scalar_one()
            if existing != row["fingerprint"]:
                raise EventCollision("event_id already exists with different content")
            return inserted is not None

    def _bigquery_write(self, row: dict[str, Any]) -> bool:
        from google.cloud import bigquery

        cfg = settings()
        client = bigquery.Client(project=cfg.google_cloud_project)
        # Batch loads avoid legacy streaming charges. Retries may append duplicates;
        # stg_events owns logical deduplication. Failed jobs can be retried with a new job ID.
        data = {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in row.items()
        }
        job = client.load_table_from_file(
            io.BytesIO((json.dumps(data) + "\n").encode()),
            f"{cfg.google_cloud_project}.{cfg.bigquery_dataset}.raw_events",
            job_id_prefix="rf_" + row["event_id"].replace("-", "") + "_",
            location=cfg.gcp_region,
            job_config=bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition="WRITE_APPEND",
            ),
        )
        job.result(timeout=90)
        return True

    def query(self, pg_sql: str, bq_sql: str | None = None) -> list[dict[str, Any]]:
        if settings().warehouse_mode == "bigquery":
            from google.cloud import bigquery

            cfg = settings()
            client = bigquery.Client(project=cfg.google_cloud_project)
            job = client.query(
                bq_sql or pg_sql,
                job_config=bigquery.QueryJobConfig(maximum_bytes_billed=cfg.maximum_bytes_billed),
            )
            return [dict(row) for row in job.result()]
        from sqlalchemy import text

        with engine(True).connect() as conn:
            return [dict(row) for row in conn.execute(text(pg_sql)).mappings()]
