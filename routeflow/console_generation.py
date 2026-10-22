"""Bounded local generation and observable, correlated ingestion progress."""

import json
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from routeflow.generation_context import generation_id

Read = Callable[..., list[dict[str, Any]]]


def stamp() -> str:
    return datetime.now(UTC).isoformat()


class Generation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID = Field(default_factory=uuid4)
    orders: int = Field(default=20, ge=1, le=500, strict=True)
    seed: int = Field(default=42, ge=0, le=9_999_999, strict=True)
    business_date: date = Field(
        default_factory=lambda: datetime.now(UTC).date() - timedelta(days=1)
    )
    transform: bool = Field(default=True, strict=True)

    @field_validator("business_date")
    @classmethod
    def bounded_date(cls, value: date) -> date:
        today = datetime.now(UTC).date()
        if not today - timedelta(days=366) <= value <= today:
            raise ValueError("Chọn ngày UTC trong 366 ngày qua, không chọn ngày tương lai.")
        return value


def counts(read: Read, identifier: str) -> dict[str, Any]:
    result: dict[str, Any] = {"source": None, "warehouse": None, "dlq": None, "events": []}
    order_ids: list[str] = []
    try:
        source = read(
            "source",
            """select count(*) as events,
            count(*) filter (where published_at is not null) as published,
            count(*) filter (where body->>'event_type'='ORDER_CREATED') as orders,
            count(*) filter (where body->>'event_type'='DRIVER_LOCATION') as gps,
            count(*) filter (where error is not null and published_at is null) as retrying,
            array_agg(aggregate_id) filter (where body->>'event_type'='ORDER_CREATED') as order_ids
            from outbox_events where body->>'correlation_id'=%s""",
            (identifier,),
        )[0]
        order_ids = source.pop("order_ids") or []
        result["source"] = source
        result["dlq"] = read(
            "source",
            """select count(*) as count from dead_letters
            where correlation_id=%s and resolved_at is null""",
            (identifier,),
        )[0]["count"]
        result["events"] = read(
            "source",
            """select event_id,body->>'event_type' as event_type,
            created_at,published_at from outbox_events where body->>'correlation_id'=%s
            order by created_at desc,event_id limit 20""",
            (identifier,),
        )
    except Exception:
        pass
    try:
        warehouse = read(
            "warehouse",
            """select count(*) as events,
            count(*) filter (where event_type='DRIVER_LOCATION') as gps
            from raw_events where event_json::jsonb->>'correlation_id'=%s""",
            (identifier,),
        )[0]
        warehouse["facts"] = None
        result["warehouse"] = warehouse
        if result["source"] is not None:
            try:
                warehouse["facts"] = read(
                    "warehouse",
                    """select count(*) as count
                    from analytics.fact_order where order_id=any(%s)""",
                    (order_ids,),
                )[0]["count"]
            except Exception:
                pass
        received = {
            row["event_id"]
            for row in read(
                "warehouse",
                """select event_id
            from raw_events where event_id=any(%s)""",
                ([row["event_id"] for row in result["events"]],),
            )
        }
        for event in result["events"]:
            event["received"] = event["event_id"] in received
    except Exception:
        pass
    return result


class Generations:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.records: dict[str, dict[str, Any]] = {}
        for path in directory.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                identifier = str(UUID(record["id"]))
                if path.stem != identifier:
                    continue
                if record["status"] == "running":
                    record["phases"] = {
                        name: "unknown" if state == "running" else state
                        for name, state in record["phases"].items()
                    }
                    record.update(
                        status="interrupted",
                        finished_at=stamp(),
                        error=(
                            "Console đã khởi động lại. Dữ liệu đã tạo vẫn giữ nguyên; "
                            "dbt có thể vẫn chạy trong API. Kiểm tra số liệu trước khi tạo đợt mới."
                        ),
                    )
                self.records[identifier] = record
                self.save(record)
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def save(self, record: dict[str, Any]) -> None:
        path = self.directory / (record["id"] + ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def running(self) -> bool:
        with self.lock:
            return any(record["status"] == "running" for record in self.records.values())

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                deepcopy(row)
                for row in sorted(
                    self.records.values(), key=lambda row: row["started_at"], reverse=True
                )[:25]
            ]

    def get(self, identifier: str) -> dict[str, Any]:
        with self.lock:
            return deepcopy(self.records[identifier])

    def create(self, body: Generation) -> tuple[dict[str, Any], bool]:
        identifier = str(body.request_id)
        options = body.model_dump(mode="json", exclude={"request_id"})
        with self.lock:
            if identifier in self.records:
                record = self.records[identifier]
                if record["options"] != options:
                    raise ValueError("Mã yêu cầu đã được dùng với cấu hình khác.")
                return deepcopy(record), False
            if self.running():
                raise ValueError("Đang chạy một đợt dữ liệu khác. Đợi hoàn tất trước khi tạo thêm.")
            record = {
                "id": identifier,
                "options": options,
                "started_at": stamp(),
                "status": "running",
                "phase": "generate",
                "error": None,
                "phases": {
                    "generate": "running",
                    "publish": "waiting",
                    "raw": "waiting",
                    "dbt": "waiting" if body.transform else "skipped",
                },
            }
            self.records[identifier] = record
            self.save(record)
            return deepcopy(record), True

    def update(self, identifier: str, **values: Any) -> None:
        with self.lock:
            self.records[identifier].update(values)
            self.save(self.records[identifier])

    def phase(self, identifier: str, name: str, state: str) -> None:
        with self.lock:
            if self.records[identifier]["phases"][name] == state:
                return
            self.records[identifier]["phases"][name] = state
            self.records[identifier]["phase"] = name
            self.save(self.records[identifier])

    def run(
        self,
        identifier: str,
        read: Read,
        transform: Callable[[], None],
        sanitize: Callable[[str], str],
        timeout: float = 180,
    ) -> None:
        from routeflow.generator import generate

        body = self.get(identifier)["options"]
        try:
            # A retried request must not append another batch, even after a console restart.
            previous = counts(read, identifier)
            if previous["source"] is None:
                raise RuntimeError("Không đọc được Source PostgreSQL.")
            if previous["source"]["events"]:
                raise RuntimeError("Đợt này đã có dữ liệu. Không tự tạo lại để tránh trùng đơn.")
            token = generation_id.set(identifier)
            try:
                outcome = generate(
                    body["orders"], body["seed"], date.fromisoformat(body["business_date"])
                )
            finally:
                generation_id.reset(token)
            self.update(identifier, outcome=outcome)
            self.phase(identifier, "generate", "success")
            self.phase(identifier, "publish", "running")
            self.phase(identifier, "raw", "running")
            deadline = time.monotonic() + timeout
            while True:
                progress = counts(read, identifier)
                source, warehouse = progress["source"], progress["warehouse"]
                if progress["dlq"]:
                    raise RuntimeError(
                        "Có sự kiện của đợt này vào DLQ. Dữ liệu đã tạo được giữ lại."
                    )
                if source and source["orders"] == body["orders"] and source["events"] > 0:
                    if source["published"] == source["events"]:
                        self.phase(identifier, "publish", "success")
                    if warehouse and warehouse["events"] == source["events"]:
                        self.phase(identifier, "raw", "success")
                        if source["published"] == source["events"]:
                            break
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "Chưa nhận đủ sự kiện vào RAW trong thời gian chờ. Kiểm tra Relay/Consumer."
                    )
                time.sleep(2)
            if body["transform"]:
                self.phase(identifier, "dbt", "running")
                transform()
                final = counts(read, identifier)
                if not final["warehouse"] or final["warehouse"]["facts"] != body["orders"]:
                    raise RuntimeError("dbt đã kết thúc nhưng mart chưa có đủ đơn của đợt này.")
                self.phase(identifier, "dbt", "success")
            self.update(identifier, status="success", phase="done", finished_at=stamp())
        except Exception as error:
            record = self.get(identifier)
            phases = dict(record["phases"])
            for name, state in phases.items():
                if state == "running":
                    phases[name] = "failed"
            self.update(
                identifier,
                status="failed",
                error=sanitize(str(error))[-2000:],
                phases=phases,
                finished_at=stamp(),
            )
