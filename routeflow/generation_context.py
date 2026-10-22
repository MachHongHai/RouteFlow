"""Propagate a UI workload ID without changing ordinary event correlations."""

from contextvars import ContextVar

generation_id: ContextVar[str | None] = ContextVar("generation_id", default=None)
