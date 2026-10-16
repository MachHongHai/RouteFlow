import json
import logging
from datetime import UTC, datetime
from typing import Any

from routeflow.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": record.name,
            "environment": settings().environment,
            "message": record.getMessage(),
        }
        for field in ("event_id", "correlation_id", "run_id", "trace_id", "lag_seconds"):
            if hasattr(record, field):
                data[field] = getattr(record, field)
        if record.exc_info:
            data["error"] = self.formatException(record.exc_info)
        return json.dumps(data)


def configure() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
