from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from routeflow.config import settings


@lru_cache
def engine(warehouse: bool = False) -> Engine:
    cfg = settings()
    url = cfg.warehouse_database_url if warehouse else cfg.source_database_url
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=2)


def session() -> Session:
    return Session(engine(), expire_on_commit=False)
