from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Zone(Identity, Base):
    __tablename__ = "delivery_zones"
    name: Mapped[str] = mapped_column(String(100), unique=True)
    traffic: Mapped[int] = mapped_column(default=1)
    __table_args__ = (CheckConstraint("traffic between 1 and 5"),)


class Customer(Identity, Base):
    __tablename__ = "customers"
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)


class Restaurant(Identity, Base):
    __tablename__ = "restaurants"
    name: Mapped[str] = mapped_column(String(100))
    zone_id: Mapped[str] = mapped_column(ForeignKey("delivery_zones.id"))


class Driver(Identity, Base):
    __tablename__ = "drivers"
    name: Mapped[str] = mapped_column(String(100))
    zone_id: Mapped[str] = mapped_column(ForeignKey("delivery_zones.id"))
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(default=1)


class Order(Identity, Base):
    __tablename__ = "orders"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    restaurant_id: Mapped[str] = mapped_column(ForeignKey("restaurants.id"))
    zone_id: Mapped[str] = mapped_column(ForeignKey("delivery_zones.id"), index=True)
    driver_id: Mapped[str | None] = mapped_column(ForeignKey("drivers.id"))
    status: Mapped[str] = mapped_column(String(40), default="ORDER_CREATED", index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    payment_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    distance_km: Mapped[int] = mapped_column(default=3)
    request_key: Mapped[str] = mapped_column(String(100), unique=True)
    __table_args__ = (
        CheckConstraint("amount_cents > 0"),
        CheckConstraint("distance_km > 0"),
        CheckConstraint("version > 0"),
        CheckConstraint("payment_status in ('PENDING','CONFIRMED','FAILED','REFUNDED')"),
    )


class OrderItem(Identity, Base):
    __tablename__ = "order_items"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("quantity > 0 and unit_price_cents > 0"),)


class Payment(Identity, Base):
    __tablename__ = "payments"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    __table_args__ = (
        CheckConstraint("amount_cents > 0"),
        CheckConstraint("status in ('CONFIRMED','FAILED','REFUNDED')"),
    )


class Assignment(Identity, Base):
    __tablename__ = "driver_assignments"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("drivers.id"), index=True)
    active: Mapped[bool] = mapped_column(default=True)
    __table_args__ = (
        Index("uq_active_order", "order_id", unique=True, postgresql_where=active),
        Index("uq_active_driver", "driver_id", unique=True, postgresql_where=active),
    )


class DriverLocation(Identity, Base):
    __tablename__ = "driver_locations"
    driver_id: Mapped[str] = mapped_column(ForeignKey("drivers.id"), index=True)
    latitude: Mapped[float]
    longitude: Mapped[float]
    __table_args__ = (
        CheckConstraint("latitude between -90 and 90 and longitude between -180 and 180"),
    )


class DeliveryEvent(Identity, Base):
    __tablename__ = "delivery_events"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    version: Mapped[int]
    __table_args__ = (UniqueConstraint("order_id", "version"),)


class Refund(Identity, Base):
    __tablename__ = "refunds"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), unique=True)
    amount_cents: Mapped[int]
    __table_args__ = (CheckConstraint("amount_cents > 0"),)


class Outbox(Base):
    __tablename__ = "outbox_events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    body: Mapped[dict[str, Any]] = mapped_column(JSON)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    aggregate_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("aggregate_id", "aggregate_version"),)


class DeadLetter(Identity, Base):
    __tablename__ = "dead_letters"
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    original_b64: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40))
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=1)
    replay_count: Mapped[int] = mapped_column(default=0)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_id: Mapped[str | None] = mapped_column(String(100))
    schema_version: Mapped[int | None]
    correlation_id: Mapped[str | None] = mapped_column(String(100))


class ProcessingFailure(Base):
    __tablename__ = "processing_failures"
    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EventIdentity(Base):
    __tablename__ = "event_identities"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PipelineRun(Identity, Base):
    __tablename__ = "pipeline_runs"
    pipeline_name: Mapped[str] = mapped_column(String(60))
    run_type: Mapped[str] = mapped_column(String(30))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    records_read: Mapped[int] = mapped_column(default=0)
    records_written: Mapped[int] = mapped_column(default=0)
    records_rejected: Mapped[int] = mapped_column(default=0)
    retry_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class Reconciliation(Identity, Base):
    __tablename__ = "reconciliation_results"
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id"), index=True)
    business_date: Mapped[str] = mapped_column(String(10))
    metric_name: Mapped[str] = mapped_column(String(60))
    source_value: Mapped[int]
    warehouse_value: Mapped[int]
    difference: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
