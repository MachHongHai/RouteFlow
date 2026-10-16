import json
import logging
from datetime import timedelta
from typing import Protocol

from sqlalchemy import or_, select

from routeflow.db import session
from routeflow.models import Outbox, now, uid


class Transport(Protocol):
    def publish(self, data: bytes) -> str: ...


def backoff(attempt: int) -> int:
    return min(300, 2 ** min(attempt, 9))


def relay_once(publisher: Transport, limit: int = 100, crash_after_publish: bool = False) -> int:
    owner = uid()
    # Claim with a short transaction; do not hold database row locks across network I/O.
    with session() as db, db.begin():
        rows = list(
            db.scalars(
                select(Outbox)
                .where(
                    Outbox.published_at.is_(None),
                    Outbox.next_attempt_at <= now(),
                    Outbox.attempts < 10,
                    or_(Outbox.lease_until.is_(None), Outbox.lease_until < now()),
                )
                .order_by(Outbox.created_at, Outbox.aggregate_version)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for row in rows:
            row.lease_owner = owner
            # Each item can take up to 30s; a batch lease covers all sequential publications.
            row.lease_until = now() + timedelta(seconds=60 + 35 * limit)
            row.attempts += 1
        work = [(row.event_id, row.body) for row in rows]
    count = 0
    for identifier, body in work:
        try:
            publisher.publish(json.dumps(body).encode())
        except Exception as exc:
            with session() as db, db.begin():
                claimed = db.scalar(
                    select(Outbox)
                    .where(Outbox.event_id == identifier, Outbox.lease_owner == owner)
                    .with_for_update()
                )
                if claimed:
                    claimed.error = str(exc)[:2000]
                    claimed.next_attempt_at = now() + timedelta(seconds=backoff(claimed.attempts))
                    claimed.lease_until = None
                    claimed.lease_owner = None
            logging.getLogger("relay").exception("Publish failed", extra={"event_id": identifier})
            continue
        if crash_after_publish:
            raise RuntimeError("Injected relay crash after publish before marking")
        with session() as db, db.begin():
            claimed = db.scalar(
                select(Outbox)
                .where(Outbox.event_id == identifier, Outbox.lease_owner == owner)
                .with_for_update()
            )
            if claimed:
                claimed.published_at = now()
                claimed.lease_until = None
                claimed.lease_owner = None
                claimed.error = None
        count += 1
    return count
