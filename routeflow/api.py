import base64
import logging
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from routeflow import domain
from routeflow.config import settings
from routeflow.db import engine, session
from routeflow.logging import configure

configure()
app = FastAPI(title="RouteFlow Delivery API", version="0.1.0")


def authorized(x_api_key: str = Header(default="")) -> None:
    import hmac

    if settings().api_key and not hmac.compare_digest(x_api_key, settings().api_key):
        raise HTTPException(401, "Invalid API key")


def database() -> Iterator[Session]:
    with session() as db, db.begin():
        yield db


DB = Annotated[Session, Depends(database)]
AUTH = [Depends(authorized)]


@app.exception_handler(domain.DomainError)
async def domain_error(request: Request, error: domain.DomainError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, error: IntegrityError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Conflicting or invalid resource"})


@app.middleware("http")
async def log_request(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    logging.getLogger("api").info(
        "%s %s %s",
        request.method,
        request.url.path,
        response.status_code,
        extra={"correlation_id": request.headers.get("x-correlation-id")},
    )
    return response


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "up"}


@app.get("/health/ready")
def ready() -> dict[str, str]:
    with engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ready"}


class Named(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CustomerInput(Named):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)


class ZoneInput(Named):
    traffic: int = Field(default=1, ge=1, le=5)


class Zoned(Named):
    zone_id: str


def serialized(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


@app.post("/customers", dependencies=AUTH, status_code=201)
def customer(body: CustomerInput, db: DB) -> dict[str, Any]:
    return serialized(domain.reference(db, "customer", body.model_dump()))


@app.post("/zones", dependencies=AUTH, status_code=201)
def zone(body: ZoneInput, db: DB) -> dict[str, Any]:
    return serialized(domain.reference(db, "zone", body.model_dump()))


@app.post("/restaurants", dependencies=AUTH, status_code=201)
def restaurant(body: Zoned, db: DB) -> dict[str, Any]:
    return serialized(domain.reference(db, "restaurant", body.model_dump()))


@app.post("/drivers", dependencies=AUTH, status_code=201)
def driver(body: Zoned, db: DB) -> dict[str, Any]:
    return serialized(domain.reference(db, "driver", body.model_dump()))


class DriverUpdate(BaseModel):
    zone_id: str


@app.patch("/drivers/{identifier}", dependencies=AUTH)
def driver_update(identifier: str, body: DriverUpdate, db: DB) -> dict[str, Any]:
    return serialized(domain.update_driver(db, identifier, body.zone_id))


class Item(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, le=100)
    unit_price_cents: int = Field(gt=0, le=100_000_000)


class OrderInput(BaseModel):
    customer_id: str
    restaurant_id: str
    items: list[Item] = Field(min_length=1, max_length=100)
    request_key: str = Field(min_length=1, max_length=100)
    distance_km: int = Field(default=3, gt=0, le=100)


@app.post("/orders", dependencies=AUTH, status_code=201)
def order(body: OrderInput, db: DB) -> dict[str, Any]:
    return serialized(domain.create_order(db, **body.model_dump()))


class StatusInput(BaseModel):
    status: str
    driver_id: str | None = None


@app.post("/orders/{identifier}/transitions", dependencies=AUTH)
def status(identifier: str, body: StatusInput, db: DB) -> dict[str, Any]:
    return serialized(domain.transition(db, identifier, body.status, body.driver_id))


class PaymentInput(BaseModel):
    success: bool = True


@app.post("/orders/{identifier}/payments", dependencies=AUTH)
def payment(identifier: str, body: PaymentInput, db: DB) -> dict[str, Any]:
    return serialized(
        domain.transition(db, identifier, "PAYMENT_CONFIRMED" if body.success else "PAYMENT_FAILED")
    )


@app.post("/orders/{identifier}/cancel", dependencies=AUTH)
def cancel(identifier: str, db: DB) -> dict[str, Any]:
    return serialized(domain.transition(db, identifier, "ORDER_CANCELLED"))


@app.post("/orders/{identifier}/refund", dependencies=AUTH)
def refund(identifier: str, db: DB) -> dict[str, Any]:
    return serialized(domain.transition(db, identifier, "REFUND_CREATED"))


class GPS(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


@app.post("/drivers/{identifier}/locations", dependencies=AUTH)
def gps(identifier: str, body: GPS, db: DB) -> dict[str, Any]:
    return serialized(domain.location(db, identifier, **body.model_dump()))


@app.post("/pubsub/push", status_code=204)
def push(body: dict[str, Any]) -> None:
    # Cloud Run IAM authenticates Pub/Sub OIDC before this private service receives requests.
    from routeflow.consumer import Consumer

    try:
        data = base64.b64decode(body["message"]["data"], validate=True)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, "Invalid Pub/Sub wrapper") from exc
    if not Consumer().process(data):
        raise HTTPException(503, "Transient ingestion failure; retry delivery")


@app.get("/metrics", dependencies=AUTH)
def metrics() -> dict[str, Any]:
    from routeflow.operations import metrics as read_metrics

    return read_metrics()
