import base64
import hashlib
import json
import logging
from typing import Any

from jsonschema import ValidationError
from sqlalchemy.dialects.postgresql import insert

from routeflow.config import settings
from routeflow.contracts import validate
from routeflow.db import session
from routeflow.models import DeadLetter, EventIdentity, ProcessingFailure, now
from routeflow.storage import Archive, EventCollision, Warehouse, canonical

logger = logging.getLogger("consumer")


class Consumer:
    def __init__(self, warehouse: Warehouse | None = None, archive: Archive | None = None) -> None:
        self.warehouse = warehouse or Warehouse()
        self.archive = archive or Archive()

    def dead_letter(self, data: bytes, category: str, error: str, attempts: int = 1) -> None:
        event: dict[str, Any] = {}
        try:
            decoded = json.loads(data)
            if isinstance(decoded, dict):
                event = decoded
        except (ValueError, UnicodeError):
            pass
        version = event.get("event_version")
        with session() as db, db.begin():
            db.execute(
                insert(DeadLetter)
                .values(
                    fingerprint=hashlib.sha256(data).hexdigest(),
                    original_b64=base64.b64encode(data).decode(),
                    category=category,
                    error=error[:4000],
                    attempts=attempts,
                    event_id=str(event.get("event_id", ""))[:100] or None,
                    schema_version=version if type(version) is int else None,
                    correlation_id=str(event.get("correlation_id", ""))[:100] or None,
                )
                .on_conflict_do_update(
                    index_elements=[DeadLetter.fingerprint],
                    set_={
                        "error": error[:4000],
                        "attempts": attempts,
                        "resolved_at": None,
                    },
                )
            )

    def process(self, data: bytes, crash_after_write: bool = False) -> bool:
        """True means durably accepted OR quarantined. False asks transport to retry."""
        try:
            self.archive.write(data)
            event = json.loads(data)
            if not isinstance(event, dict):
                raise ValueError("Envelope must be an object")
            validate(event)
            fingerprint = hashlib.sha256(canonical(event).encode()).hexdigest()
            with session() as db, db.begin():
                db.execute(
                    insert(EventIdentity)
                    .values(event_id=event["event_id"], fingerprint=fingerprint)
                    .on_conflict_do_nothing()
                )
                identity = db.get(EventIdentity, event["event_id"])
                if identity is None or identity.fingerprint != fingerprint:
                    raise EventCollision("Producer reused event_id with different content")
            inserted = self.warehouse.write(event)
            if crash_after_write:
                raise RuntimeError("Injected consumer crash before acknowledgement")
            lag = (
                now()
                - __import__("datetime").datetime.fromisoformat(
                    event["event_time"].replace("Z", "+00:00")
                )
            ).total_seconds()
            logger.info(
                "Event ingested" if inserted else "Duplicate event",
                extra={
                    "event_id": event["event_id"],
                    "correlation_id": event["correlation_id"],
                    "lag_seconds": lag,
                },
            )
            return True
        except (ValidationError, ValueError, UnicodeError, EventCollision) as exc:
            try:
                self.dead_letter(data, "INVALID_CONTRACT", str(exc))
                logger.warning("Event quarantined: INVALID_CONTRACT")
                return True
            except Exception:
                logger.exception("DLQ unavailable")
                return False
        except Exception as exc:
            logger.exception("Transient ingestion failure")
            try:
                with session() as db, db.begin():
                    statement = insert(ProcessingFailure).values(
                        fingerprint=hashlib.sha256(data).hexdigest(), attempts=1, error=str(exc)
                    )
                    count = db.scalar(
                        statement.on_conflict_do_update(
                            index_elements=[ProcessingFailure.fingerprint],
                            set_={
                                "attempts": ProcessingFailure.attempts + 1,
                                "error": str(exc)[:4000],
                                "updated_at": now(),
                            },
                        ).returning(ProcessingFailure.attempts)
                    )
                if count is not None and count >= settings().max_processing_attempts:
                    # Archive failure still preserves exact original bytes in the durable DLQ.
                    self.dead_letter(data, "RETRY_EXHAUSTED", str(exc), count)
                    return True
            except Exception:
                logger.exception("Failure counter unavailable; transport retains message")
            return False
