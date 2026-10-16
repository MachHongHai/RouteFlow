import base64
import json
import logging
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

from routeflow.config import settings
from routeflow.consumer import Consumer
from routeflow.db import engine, session
from routeflow.models import (
    DeadLetter,
    Order,
    Outbox,
    Payment,
    PipelineRun,
    ProcessingFailure,
    Reconciliation,
    now,
)
from routeflow.storage import Archive, Warehouse

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def pipeline(name: str, kind: str = "scheduled") -> Iterator[PipelineRun]:
    with session() as db, db.begin():
        run = PipelineRun(pipeline_name=name, run_type=kind)
        db.add(run)
        db.flush()
        db.expunge(run)
    logging.getLogger("operations").info("Pipeline started: %s", name, extra={"run_id": run.id})
    try:
        yield run
        run.status = "SUCCESS"
    except Exception as exc:
        run.status = "FAILED"
        run.error_message = str(exc)[:4000]
        raise
    finally:
        run.finished_at = now()
        with session() as db, db.begin():
            db.merge(run)
        logging.getLogger("operations").info(
            "Pipeline %s: %s", run.status, name, extra={"run_id": run.id}
        )


def dbt_build(variables: dict[str, str] | None = None, full_refresh: bool = False) -> None:
    with pipeline("dbt", "full_refresh" if full_refresh else "incremental") as run:
        command = [
            sys.executable,
            "-c",
            "from dbt.cli.main import cli; cli()",
            "build",
            "--project-dir",
            str(ROOT / "dbt"),
            "--profiles-dir",
            str(ROOT / "dbt"),
            "--target",
            "cloud" if settings().warehouse_mode == "bigquery" else "local",
        ]
        if variables:
            command.extend(["--vars", json.dumps(variables)])
        if full_refresh:
            command.append("--full-refresh")
        subprocess.run(command, check=True, cwd=ROOT)
        result_path = ROOT / "dbt/target/run_results.json"
        if result_path.exists():
            results = json.loads(result_path.read_text())["results"]
            run.records_read = len(results)
            run.records_written = sum(result["status"] in ("success", "pass") for result in results)


def validate_range(start: date, end: date) -> None:
    if end < start:
        raise ValueError("--to must be on or after --from")
    if (end - start).days > 366:
        raise ValueError("Backfill is limited to 367 inclusive business dates per run")
    if end > now().date():
        raise ValueError("Cannot backfill future business dates")


def replay(start: date | None = None, end: date | None = None) -> dict[str, int]:
    with pipeline("archive_replay", "replay") as run:
        consumer = Consumer()

        # Snapshot iterator before writes: replay does not produce another archive generation.
        class ArchivedInput(Archive):
            def write(self, data: bytes) -> str:
                return "already-durable-archive"

        consumer.archive = ArchivedInput()
        for data in Archive().read():
            if start or end:
                try:
                    event_day = datetime.fromisoformat(json.loads(data)["event_time"]).date()
                except (ValueError, KeyError, TypeError):
                    continue
                if (start and event_day < start) or (end and event_day > end):
                    continue
            run.records_read += 1
            if not consumer.process(data):
                raise RuntimeError("Replay failed; input retained in archive")
            run.records_written += 1
        return {"read": run.records_read, "accepted": run.records_written}


def backfill(start: date, end: date) -> dict[str, int]:
    validate_range(start, end)
    with pipeline("backfill", "backfill") as run:
        results = replay(start, end)
        run.records_read = results["read"]
        run.records_written = results["accepted"]
        dbt_build({"backfill_from": start.isoformat(), "backfill_to": end.isoformat()})
        return results


def dlq_replay(limit: int = 100) -> int:
    with pipeline("dlq_replay", "replay") as run:
        with session() as db:
            rows = list(
                db.scalars(
                    select(DeadLetter)
                    .where(DeadLetter.resolved_at.is_(None))
                    .order_by(DeadLetter.created_at)
                    .limit(limit)
                )
            )
        for row in rows:
            data = base64.b64decode(row.original_b64)
            # Reset processing budget for an explicit operator replay.
            with session() as db, db.begin():
                failure = db.get(ProcessingFailure, row.fingerprint)
                if failure:
                    failure.attempts = 0
                current = db.get(DeadLetter, row.id)
                assert current is not None
                current.replay_count += 1
                current.resolved_at = now()
            run.records_read += 1
            accepted = Consumer().process(data)
            with session() as db, db.begin():
                current = db.get(DeadLetter, row.id)
                assert current is not None
                if not accepted:
                    current.resolved_at = None
                if current.resolved_at:
                    run.records_written += 1
                else:
                    run.records_rejected += 1
        return run.records_written


def reconcile(business_date: date | None = None, grace_seconds: int = 60) -> dict[str, Any]:
    cutoff = now() - timedelta(seconds=grace_seconds)
    with pipeline("reconciliation") as run:
        with session() as db:
            query = select(Order).where(Order.created_at <= cutoff)
            if business_date:
                start = datetime.combine(business_date, datetime.min.time(), tzinfo=UTC)
                query = query.where(
                    Order.created_at >= start, Order.created_at < start + timedelta(days=1)
                )
            orders = list(db.scalars(query))
            # Recently changing orders are not yet eligible for a comparison of current state.
            excluded = {order.id for order in orders if order.updated_at > cutoff}
            stable = {order.id: order for order in orders if order.id not in excluded}
            payments = list(db.scalars(select(Payment)))
        cfg = settings()
        fact_table = "analytics.fact_order"
        cloud_fact = f"`{cfg.google_cloud_project}.routeflow_analytics.fact_order`"
        rows = Warehouse().query(f"select * from {fact_table}", f"select * from {cloud_fact}")
        # Older local dbt tables may use timestamp-without-time-zone; their values are UTC.
        for row in rows:
            if row["created_at"].tzinfo is None:
                row["created_at"] = row["created_at"].replace(tzinfo=UTC)
        curated = {
            row["order_id"]: row
            for row in rows
            if row["order_id"] not in excluded
            and row["created_at"] <= cutoff
            and (business_date is None or row["created_at"].date() == business_date)
        }
        source_metrics = {
            "order_count": len(stable),
            "payment_count": sum(payment.order_id in stable for payment in payments),
            "gross_amount_cents": sum(order.amount_cents for order in stable.values()),
            "delivered_count": 0,
            "cancelled_count": 0,
        }
        # Refund events may follow delivered/cancelled states; history is the durable source.
        from routeflow.models import DeliveryEvent

        with session() as db:
            history = list(db.execute(select(DeliveryEvent.order_id, DeliveryEvent.status)))
        delivered = {identifier for identifier, status in history if status == "DELIVERED"}
        cancelled = {identifier for identifier, status in history if status == "ORDER_CANCELLED"}
        source_metrics["delivered_count"] = len(delivered & stable.keys())
        source_metrics["cancelled_count"] = len(cancelled & stable.keys())
        warehouse_metrics = {
            "order_count": len(curated),
            "payment_count": sum(row["payment_id"] is not None for row in curated.values()),
            "gross_amount_cents": sum(row["amount_cents"] for row in curated.values()),
            "delivered_count": sum(row["delivered_at"] is not None for row in curated.values()),
            "cancelled_count": sum(row["cancelled_at"] is not None for row in curated.values()),
        }
        missing = sorted(stable.keys() - curated.keys())
        unexpected = sorted(curated.keys() - stable.keys())
        mismatched = [
            identifier
            for identifier in stable.keys() & curated.keys()
            if stable[identifier].status != curated[identifier]["status"]
            or stable[identifier].amount_cents != curated[identifier]["amount_cents"]
        ]
        results = {}
        with session() as db, db.begin():
            for metric, source_value in source_metrics.items():
                warehouse_value = int(warehouse_metrics[metric])
                status = "PASS" if source_value == warehouse_value else "FAIL"
                results[metric] = status
                db.add(
                    Reconciliation(
                        run_id=run.id,
                        business_date=str(business_date or "all"),
                        metric_name=metric,
                        source_value=source_value,
                        warehouse_value=warehouse_value,
                        difference=warehouse_value - source_value,
                        status=status,
                        details={
                            "missing_ids": missing[:100],
                            "unexpected_ids": unexpected[:100],
                            "mismatched_ids": mismatched[:100],
                            "cutoff": cutoff.isoformat(),
                        },
                    )
                )
            record_ok = not (missing or unexpected or mismatched)
            results["record_consistency"] = "PASS" if record_ok else "FAIL"
            db.add(
                Reconciliation(
                    run_id=run.id,
                    business_date=str(business_date or "all"),
                    metric_name="record_consistency",
                    source_value=0,
                    warehouse_value=len(missing) + len(unexpected) + len(mismatched),
                    difference=len(missing) + len(unexpected) + len(mismatched),
                    status=results["record_consistency"],
                    details={
                        "missing_ids": missing[:100],
                        "unexpected_ids": unexpected[:100],
                        "mismatched_ids": mismatched[:100],
                    },
                )
            )
        run.records_read = len(stable)
        run.records_rejected = sum(status == "FAIL" for status in results.values())
        if run.records_rejected:
            raise ValueError(f"Reconciliation mismatch: {results}")
        return results


def metrics() -> dict[str, Any]:
    with session() as db:
        backlog = db.scalar(
            select(func.count()).select_from(Outbox).where(Outbox.published_at.is_(None))
        )
        exhausted = db.scalar(
            select(func.count())
            .select_from(Outbox)
            .where(Outbox.published_at.is_(None), Outbox.attempts >= 10)
        )
        dlq = db.scalar(
            select(func.count()).select_from(DeadLetter).where(DeadLetter.resolved_at.is_(None))
        )
        failed_runs = db.scalar(
            select(func.count()).select_from(PipelineRun).where(PipelineRun.status == "FAILED")
        )
        processing_failures = db.scalar(
            select(func.coalesce(func.sum(ProcessingFailure.attempts), 0))
        )
        reconciliation_failures = db.scalar(
            select(func.count()).select_from(Reconciliation).where(Reconciliation.status == "FAIL")
        )
        last_run = db.scalar(select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(1))
        last_duration = (
            (last_run.finished_at - last_run.created_at).total_seconds()
            if last_run and last_run.finished_at
            else None
        )
    cfg = settings()
    if cfg.warehouse_mode == "postgres":
        sql = """select count(*) as events, max(ingested_at) as freshest_ingestion,
          avg(extract(epoch from (ingested_at-event_time))) as avg_lag_seconds from raw_events"""
        raw = Warehouse().query(sql)[0]
        with engine(True).connect() as conn:
            attempts = conn.scalar(text("select count(*) from raw_delivery_attempts")) or 0
        raw["delivery_attempts"] = attempts
        raw["duplicate_rate"] = (attempts - raw["events"]) / attempts if attempts else 0
    else:
        table = f"`{cfg.google_cloud_project}.{cfg.bigquery_dataset}.raw_events`"
        raw = Warehouse().query(
            f"select count(*) as events, max(ingested_at) as freshest_ingestion, "
            f"avg(timestamp_diff(ingested_at,event_time,SECOND)) as avg_lag_seconds from {table}"
        )[0]
    return {
        "outbox_backlog": backlog,
        "outbox_exhausted": exhausted,
        "dlq_open": dlq,
        "failed_pipeline_runs": failed_runs,
        "processing_failures_total": processing_failures,
        "reconciliation_failures": reconciliation_failures,
        "last_pipeline_duration_seconds": last_duration,
        **raw,
    }
