import argparse
import json
import signal
import threading
from datetime import date

from sqlalchemy import select

from routeflow.db import session
from routeflow.logging import configure
from routeflow.models import Outbox


def main() -> None:
    configure()
    parser = argparse.ArgumentParser(description="RouteFlow pipeline operations")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "init",
        "seed",
        "provision",
        "consume",
        "metrics",
        "batch",
        "replay",
        "outbox-reset",
        "wait-ingestion",
    ):
        sub.add_parser(name)
    transforms = sub.add_parser("dbt")
    transforms.add_argument("--full-refresh", action="store_true")
    relay = sub.add_parser("relay")
    relay.add_argument("--watch", action="store_true")
    relay.add_argument("--limit", type=int, default=100)
    dlq = sub.add_parser("dlq-replay")
    dlq.add_argument("--limit", type=int, default=100)
    fill = sub.add_parser("backfill")
    fill.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    fill.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    spark_fill = sub.add_parser("spark-backfill")
    spark_fill.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    spark_fill.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    spark_fill.add_argument("--explain", action="store_true")
    recon = sub.add_parser("reconcile")
    recon.add_argument("--date", type=date.fromisoformat)
    recon.add_argument("--grace-seconds", type=int, default=60)
    args = parser.parse_args()
    from routeflow import operations
    from routeflow.consumer import Consumer
    from routeflow.generator import generate, seed
    from routeflow.messaging import Publisher, consume, provision
    from routeflow.relay import relay_once
    from routeflow.storage import Warehouse

    result: object = None
    match args.command:
        case "init":
            Warehouse().init()
        case "seed":
            seed()
        case "provision":
            provision()
        case "consume":
            consume(Consumer().process)
        case "relay":
            stop = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            signal.signal(signal.SIGINT, lambda *_: stop.set())
            publisher = Publisher()
            while True:
                result = relay_once(publisher, args.limit)
                if not args.watch or stop.wait(1):
                    break
        case "outbox-reset":
            with session() as db, db.begin():
                for row in db.scalars(
                    select(Outbox)
                    .where(Outbox.published_at.is_(None), Outbox.attempts >= 10)
                    .with_for_update()
                ):
                    row.attempts = 0
                    row.lease_until = None
            result = "Reset exhausted unpublished outbox rows"
        case "dlq-replay":
            result = operations.dlq_replay(args.limit)
        case "replay":
            result = operations.replay()
        case "backfill":
            result = operations.backfill(args.start, args.end)
        case "spark-backfill":
            import os
            import subprocess

            operations.validate_range(args.start, args.end)
            if os.environ.get("SPARK_HOME"):
                from routeflow.spark.job import run

                result = run(args.start, args.end, args.explain)
            else:
                command = [
                    "docker",
                    "compose",
                    "--profile",
                    "spark",
                    "run",
                    "--rm",
                    "--use-aliases",
                    "spark-job",
                    "--from",
                    str(args.start),
                    "--to",
                    str(args.end),
                ]
                if args.explain:
                    command.append("--explain")
                subprocess.run(command, check=True)
        case "reconcile":
            result = operations.reconcile(args.date, args.grace_seconds)
        case "metrics":
            result = operations.metrics()
        case "wait-ingestion":
            from routeflow.cloud_job import wait_ingestion

            result = {"verified_events": wait_ingestion()}
        case "dbt":
            operations.dbt_build(full_refresh=args.full_refresh)
        case "batch":
            # Shared orchestration; Cloud Run Jobs invoke bounded operations and exit.
            generate(10)
            publisher = Publisher()
            while relay_once(publisher):
                pass
            from routeflow.cloud_job import wait_ingestion

            wait_ingestion()
            operations.dbt_build()
            result = operations.reconcile()
    if result is not None:
        print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
