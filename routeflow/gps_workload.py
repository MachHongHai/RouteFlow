"""Configurable GPS tracks through the actual domain/outbox, suitable for Spark benchmarks."""

import argparse
import json
import random
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from routeflow.db import session
from routeflow.domain import location
from routeflow.generator import seed
from routeflow.models import Driver, now


def generate(points: int, seed_value: int = 42) -> dict[str, int | float]:
    if not 1 <= points <= 1_000_000:
        raise ValueError("points must be 1..1000000; start with 1000 locally")
    seed()
    rng = random.Random(seed_value)
    with session() as db:
        drivers = list(db.scalars(select(Driver).order_by(Driver.name)))
    start = datetime.combine((now() - timedelta(days=1)).date(), datetime.min.time(), tzinfo=UTC)
    positions = {driver.id: [10.77 + i / 100, 106.67] for i, driver in enumerate(drivers)}
    started = time.monotonic()
    for chunk in range(0, points, 500):
        with session() as db, db.begin():
            for index in range(chunk, min(chunk + 500, points)):
                driver = drivers[index % len(drivers)]
                position = positions[driver.id]
                position[0] += rng.uniform(0.00001, 0.00006)
                position[1] += rng.uniform(-0.00002, 0.00005)
                at = start + timedelta(seconds=(index // len(drivers)) * 10)
                location(db, driver.id, position[0], position[1], at)
    return {"generated_points": points, "elapsed_seconds": round(time.monotonic() - started, 3)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(generate(args.points, args.seed)))


if __name__ == "__main__":
    main()
