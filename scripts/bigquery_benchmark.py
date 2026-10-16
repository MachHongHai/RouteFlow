"""Dry run by default. --execute opts into bounded BigQuery query billing."""

import argparse
import json

from google.cloud import bigquery


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--maximum-bytes-billed", type=int, default=100_000_000)
    args = parser.parse_args()
    client = bigquery.Client(project=args.project)
    table = f"`{args.project}.routeflow_raw.raw_events`"
    for label, predicate in [
        ("unpruned", "date(timestamp(json_value(event_json,'$.event_time')))=@day"),
        (
            "pruned",
            "event_time >= timestamp(@day) and "
            "event_time < timestamp(date_add(@day,interval 1 day))",
        ),
    ]:
        config = bigquery.QueryJobConfig(
            dry_run=not args.execute,
            use_query_cache=False,
            maximum_bytes_billed=args.maximum_bytes_billed,
            query_parameters=[bigquery.ScalarQueryParameter("day", "DATE", args.date)],
        )
        job = client.query(
            f"select event_type, count(*) as events from {table} "
            f"where {predicate} group by event_type",
            job_config=config,
        )
        if args.execute:
            list(job.result())
        print(
            json.dumps(
                {
                    "query": label,
                    "dry_run": not args.execute,
                    "bytes_processed": job.total_bytes_processed,
                    "slot_millis": job.slot_millis,
                    "started": str(job.started),
                    "ended": str(job.ended),
                }
            )
        )


if __name__ == "__main__":
    main()
