"""Host orchestration: stream -> ingestion barrier -> optional Spark -> dbt -> reconcile."""

import argparse
import subprocess
from datetime import UTC, datetime, timedelta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", type=int, default=20)
    parser.add_argument("--spark", action="store_true")
    args = parser.parse_args()
    prefix = ["docker", "compose", "exec", "-T", "api", "python", "-m"]
    subprocess.run(prefix + ["routeflow.generator", "--orders", str(args.orders)], check=True)
    subprocess.run(prefix + ["routeflow.cli", "wait-ingestion"], check=True)
    if args.spark:
        day = str((datetime.now(UTC) - timedelta(days=1)).date())
        subprocess.run(
            [
                "docker",
                "compose",
                "--profile",
                "spark",
                "run",
                "--rm",
                "--use-aliases",
                "spark-job",
                "--from",
                day,
                "--to",
                day,
            ],
            check=True,
        )
    subprocess.run(prefix + ["routeflow.cli", "dbt"], check=True)
    subprocess.run(prefix + ["routeflow.cli", "reconcile", "--grace-seconds", "0"], check=True)


if __name__ == "__main__":
    main()
