"""Reproducible business workloads. Fault injection lives separately in chaos.py."""

import argparse
import json
import random
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from routeflow import domain
from routeflow.db import session
from routeflow.models import Customer, Driver, Restaurant, Zone, now, uid


def seed() -> None:
    with session() as db, db.begin():
        if db.scalar(select(Zone.id).limit(1)):
            return
        at = now() - timedelta(days=30)
        for index, (name, traffic) in enumerate(
            [("District 1", 3), ("Thu Duc", 2), ("District 7", 1)]
        ):
            zone = domain.reference(db, "zone", {"name": name, "traffic": traffic}, at)
            domain.reference(db, "restaurant", {"name": f"Kitchen {index}", "zone_id": zone.id}, at)
            for number in range(3):
                domain.reference(
                    db, "driver", {"name": f"Driver {index}-{number}", "zone_id": zone.id}, at
                )
        for index in range(12):
            domain.reference(
                db,
                "customer",
                {"name": f"Customer {index}", "email": f"customer{index}@routeflow.example"},
                at,
            )


def generate(
    orders: int, seed_value: int = 42, business_date: date | None = None
) -> dict[str, int]:
    if orders < 1 or orders > 10_000:
        raise ValueError("orders must be between 1 and 10000")
    seed()
    rng = random.Random(seed_value)
    day = business_date or (now() - timedelta(days=1)).date()
    counts: dict[str, int] = {}
    # Invocation IDs differ; business outcomes are reproducible for the same seed.
    batch_id = uid()
    with session() as db:
        customers = list(db.scalars(select(Customer).order_by(Customer.email)))
        restaurants = list(db.scalars(select(Restaurant).order_by(Restaurant.name)))
    for index in range(orders):
        hour = rng.choices(
            list(range(8, 23)), weights=[1, 1, 2, 5, 6, 4, 2, 1, 2, 5, 6, 5, 3, 2, 1]
        )[0]
        at = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(
            hours=hour, minutes=rng.randrange(60)
        )
        peak = hour in (11, 12, 17, 18, 19)
        restaurant = rng.choice(restaurants)
        customer = rng.choice(customers)
        distance = rng.randint(1, 10)
        with session() as db, db.begin():
            zone: Zone = domain.require(db, Zone, restaurant.zone_id)
            order = domain.create_order(
                db,
                customer.id,
                restaurant.id,
                [
                    {
                        "name": "Meal",
                        "quantity": rng.randint(1, 3),
                        "unit_price_cents": rng.choice([3500, 4500, 6000]),
                    }
                ],
                f"{batch_id}-{index}",
                distance,
                at,
            )
            at += timedelta(seconds=rng.randint(1, 5))

            def step(status: str, driver_id: str | None = None) -> None:
                domain.transition(db, order.id, status, driver_id, at)  # noqa: B023

            if rng.random() < 0.06:
                step("PAYMENT_FAILED")
                step("ORDER_CANCELLED")
            else:
                step("PAYMENT_CONFIRMED")
                if rng.random() < 0.08:
                    step("ORDER_CANCELLED")
                    step("REFUND_CREATED")
                else:
                    at += timedelta(minutes=rng.randint(2, 8))
                    step("RESTAURANT_ACCEPTED")
                    drivers = list(
                        db.scalars(
                            select(Driver)
                            .where(Driver.zone_id == zone.id, Driver.available.is_(True))
                            .order_by(Driver.name)
                        )
                    )
                    if not drivers:
                        step("ORDER_CANCELLED")
                        step("REFUND_CREATED")
                    else:
                        driver = rng.choice(drivers)
                        at += timedelta(minutes=rng.randint(1, 4) * (2 if peak else 1))
                        step("DRIVER_ASSIGNED", driver.id)
                        if rng.random() < 0.04:
                            step("DRIVER_CANCELLED")
                            at += timedelta(minutes=3)
                            step("DRIVER_ASSIGNED", driver.id)
                        at += timedelta(minutes=rng.randint(2, 6))
                        step("DRIVER_ARRIVED")
                        at += timedelta(minutes=rng.randint(3, 12))
                        step("ORDER_PICKED_UP")
                        step("IN_TRANSIT")
                        domain.location(
                            db, driver.id, 10.77 + rng.random() / 20, 106.65 + rng.random() / 20, at
                        )
                        at += timedelta(minutes=distance * (zone.traffic + (2 if peak else 0)))
                        domain.location(
                            db, driver.id, 10.77 + rng.random() / 20, 106.65 + rng.random() / 20, at
                        )
                        step("DELIVERED")
            counts[order.status] = counts.get(order.status, 0) + 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--business-date", type=date.fromisoformat)
    parser.add_argument(
        "--mode",
        choices=[
            "normal",
            "duplicate_events",
            "late_events",
            "out_of_order_events",
            "invalid_schema",
            "missing_required_fields",
            "consumer_failures",
        ],
        default="normal",
    )
    args = parser.parse_args()
    print(json.dumps(generate(args.orders, args.seed, args.business_date)))
    if args.mode != "normal":
        from routeflow.chaos import run

        print(json.dumps(run(args.mode.replace("_", "-"))))


if __name__ == "__main__":
    main()
