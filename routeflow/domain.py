from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from routeflow.contracts import validate
from routeflow.models import (
    Assignment,
    Customer,
    DeliveryEvent,
    Driver,
    DriverLocation,
    Order,
    OrderItem,
    Outbox,
    Payment,
    Refund,
    Restaurant,
    Zone,
    now,
    uid,
)

TRANSITIONS: dict[str, set[str]] = {
    "ORDER_CREATED": {"PAYMENT_CONFIRMED", "PAYMENT_FAILED", "ORDER_CANCELLED"},
    "PAYMENT_CONFIRMED": {"RESTAURANT_ACCEPTED", "ORDER_CANCELLED"},
    "RESTAURANT_ACCEPTED": {"DRIVER_ASSIGNED", "ORDER_CANCELLED"},
    "DRIVER_ASSIGNED": {"DRIVER_ARRIVED", "DRIVER_CANCELLED", "ORDER_CANCELLED"},
    "DRIVER_CANCELLED": {"DRIVER_ASSIGNED", "ORDER_CANCELLED"},
    "DRIVER_ARRIVED": {"ORDER_PICKED_UP", "ORDER_CANCELLED"},
    "ORDER_PICKED_UP": {"IN_TRANSIT"},
    "IN_TRANSIT": {"DELIVERED"},
    "PAYMENT_FAILED": {"ORDER_CANCELLED"},
    "ORDER_CANCELLED": {"REFUND_CREATED"},
    "DELIVERED": {"REFUND_CREATED"},
}


class DomainError(ValueError):
    """A business invariant was violated; transaction must be rolled back."""


def require(db: Session, model: Any, identifier: str, lock: bool = False) -> Any:
    query = select(model).where(model.id == identifier)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise DomainError(f"{model.__name__} {identifier} does not exist")
    return row


def emit(
    db: Session,
    kind: str,
    aggregate_id: str,
    version: int,
    payload: dict[str, Any],
    at: datetime | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    event = {
        "event_id": uid(),
        "event_type": kind,
        "event_version": 1,
        "aggregate_id": aggregate_id,
        "aggregate_version": version,
        "event_time": (at or now()).isoformat(),
        "produced_at": now().isoformat(),
        "producer": "delivery-api",
        "correlation_id": correlation_id or aggregate_id,
        "payload": payload,
    }
    validate(event)
    db.add(
        Outbox(
            event_id=event["event_id"],
            body=event,
            aggregate_id=aggregate_id,
            aggregate_version=version,
        )
    )
    return event


def reference(db: Session, kind: str, data: dict[str, Any], at: datetime | None = None) -> Any:
    models = {"zone": Zone, "customer": Customer, "restaurant": Restaurant, "driver": Driver}
    model: Any = models[kind]
    if "zone_id" in data:
        require(db, Zone, data["zone_id"])
    row = model(**data, created_at=at or now())
    db.add(row)
    db.flush()
    payload = {
        column.name: getattr(row, column.name)
        for column in model.__table__.columns
        if column.name != "created_at"
    }
    emit(db, f"{kind.upper()}_UPDATED", row.id, 1, payload, at)
    return row


def update_driver(db: Session, identifier: str, zone_id: str, at: datetime | None = None) -> Driver:
    driver: Driver = require(db, Driver, identifier, lock=True)
    require(db, Zone, zone_id)
    if not driver.available:
        raise DomainError("Cannot relocate an assigned driver")
    driver.zone_id = zone_id
    driver.version += 1
    emit(
        db,
        "DRIVER_UPDATED",
        driver.id,
        driver.version,
        {"id": driver.id, "name": driver.name, "zone_id": zone_id},
        at,
    )
    return driver


def order_payload(db: Session, order: Order) -> dict[str, Any]:
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    return {
        "order_id": order.id,
        "customer_id": order.customer_id,
        "restaurant_id": order.restaurant_id,
        "zone_id": order.zone_id,
        "driver_id": order.driver_id,
        "status": order.status,
        "amount_cents": order.amount_cents,
        "payment_status": order.payment_status,
        "payment_id": payment.id if payment else None,
        "distance_km": order.distance_km,
        "created_at": order.created_at.isoformat(),
    }


def create_order(
    db: Session,
    customer_id: str,
    restaurant_id: str,
    items: list[dict[str, Any]],
    request_key: str,
    distance_km: int = 3,
    at: datetime | None = None,
) -> Order:
    existing = db.scalar(select(Order).where(Order.request_key == request_key))
    if existing:
        expected = sum(item["quantity"] * item["unit_price_cents"] for item in items)
        existing_items = sorted(
            (row.name, row.quantity, row.unit_price_cents)
            for row in db.scalars(select(OrderItem).where(OrderItem.order_id == existing.id))
        )
        requested_items = sorted(
            (item["name"], item["quantity"], item["unit_price_cents"]) for item in items
        )
        if (
            existing.customer_id,
            existing.restaurant_id,
            existing.amount_cents,
            existing.distance_km,
        ) != (
            customer_id,
            restaurant_id,
            expected,
            distance_km,
        ) or existing_items != requested_items:
            raise DomainError("Idempotency key reused with a different order")
        return existing
    require(db, Customer, customer_id)
    restaurant: Restaurant = require(db, Restaurant, restaurant_id)
    if not items or any(item["quantity"] <= 0 or item["unit_price_cents"] <= 0 for item in items):
        raise DomainError("An order needs positive quantities and prices")
    order = Order(
        customer_id=customer_id,
        restaurant_id=restaurant.id,
        zone_id=restaurant.zone_id,
        amount_cents=sum(item["quantity"] * item["unit_price_cents"] for item in items),
        distance_km=distance_km,
        request_key=request_key,
        created_at=at or now(),
        updated_at=at or now(),
    )
    db.add(order)
    db.flush()
    for item in items:
        db.add(OrderItem(order_id=order.id, **item, created_at=order.created_at))
    db.add(
        DeliveryEvent(
            order_id=order.id, status=order.status, version=1, created_at=order.created_at
        )
    )
    emit(db, "ORDER_CREATED", order.id, 1, order_payload(db, order), order.created_at)
    return order


def transition(
    db: Session,
    order_id: str,
    target: str,
    driver_id: str | None = None,
    at: datetime | None = None,
) -> Order:
    order: Order = require(db, Order, order_id, lock=True)
    if target not in TRANSITIONS.get(order.status, set()):
        raise DomainError(f"Invalid transition {order.status} -> {target}")
    when = at or now()
    if when < order.updated_at:
        raise DomainError("Business event time cannot move backwards")
    if target in ("PAYMENT_CONFIRMED", "PAYMENT_FAILED"):
        order.payment_status = "CONFIRMED" if target == "PAYMENT_CONFIRMED" else "FAILED"
        db.add(
            Payment(
                order_id=order.id,
                amount_cents=order.amount_cents,
                status=order.payment_status,
                created_at=when,
            )
        )
    if target == "DRIVER_ASSIGNED":
        if driver_id is None:
            raise DomainError("driver_id is required")
        driver: Driver = require(db, Driver, driver_id, lock=True)
        if not driver.available or driver.zone_id != order.zone_id:
            raise DomainError("Driver unavailable or outside order zone")
        driver.available = False
        order.driver_id = driver.id
        db.add(Assignment(order_id=order.id, driver_id=driver.id, created_at=when))
    if target in ("DRIVER_CANCELLED", "ORDER_CANCELLED", "DELIVERED") and order.driver_id:
        driver = require(db, Driver, order.driver_id, lock=True)
        driver.available = True
        assignment = db.scalar(
            select(Assignment).where(Assignment.order_id == order.id, Assignment.active.is_(True))
        )
        if assignment:
            assignment.active = False
        if target == "DRIVER_CANCELLED":
            order.driver_id = None
    if target == "REFUND_CREATED":
        payment = db.scalar(select(Payment).where(Payment.order_id == order.id).with_for_update())
        if payment is None or payment.status != "CONFIRMED":
            raise DomainError("Only confirmed, unrefunded payments can be refunded")
        db.add(
            Refund(
                order_id=order.id,
                payment_id=payment.id,
                amount_cents=payment.amount_cents,
                created_at=when,
            )
        )
        payment.status = "REFUNDED"
        order.payment_status = "REFUNDED"
    order.version += 1
    order.status = target
    order.updated_at = when
    db.flush()
    db.add(DeliveryEvent(order_id=order.id, status=target, version=order.version, created_at=when))
    emit(db, target, order.id, order.version, order_payload(db, order), when)
    return order


def location(
    db: Session, driver_id: str, latitude: float, longitude: float, at: datetime | None = None
) -> DriverLocation:
    driver: Driver = require(db, Driver, driver_id)
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise DomainError("Invalid GPS coordinates")
    row = DriverLocation(
        driver_id=driver_id, latitude=latitude, longitude=longitude, created_at=at or now()
    )
    db.add(row)
    db.flush()
    emit(
        db,
        "DRIVER_LOCATION",
        row.id,
        1,
        {
            "driver_id": driver_id,
            "zone_id": driver.zone_id,
            "latitude": latitude,
            "longitude": longitude,
        },
        at,
    )
    return row
