"""Local schema explorer and bounded SQL using a separate, SELECT-only database role."""

import json
import os
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException
from psycopg import sql
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import URL, make_url

from routeflow.config import settings

Database = Literal["source", "warehouse"]
ROLE = "routeflow_console_reader"
SCHEMAS = ("public", "staging", "intermediate", "analytics", "snapshots")
router = APIRouter(prefix="/api/database")
provision_lock = threading.Lock()
query_slots = threading.BoundedSemaphore(2)
prepared: dict[str, float] = {}


def local_url(database: Database) -> URL:
    cfg = settings()
    if cfg.environment != "local" or cfg.warehouse_mode != "postgres":
        raise HTTPException(409, "Trình truy vấn chỉ hỗ trợ PostgreSQL local.")
    url = make_url(cfg.source_database_url if database == "source" else cfg.warehouse_database_url)
    hosts: set[str] = (
        {database}
        if os.getenv("ROUTEFLOW_CONSOLE_CONTAINER") == "1"
        else {"localhost", "127.0.0.1", "::1"}
    )
    if url.host not in hosts:
        raise HTTPException(409, "Database không nằm trong kết nối local được phép.")
    return url.set(drivername="postgresql")


def reader_password() -> str:
    directory = (
        Path("/var/lib/routeflow-console")
        if os.getenv("ROUTEFLOW_CONSOLE_CONTAINER") == "1"
        else Path(__file__).resolve().parent.parent / ".local/console/generation"
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sql-reader.key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()


def provision(database: Database, url: URL) -> str:
    with provision_lock:
        password = reader_password()
        if time.monotonic() - prepared.get(database, float("-inf")) < 60:
            return password
        with psycopg.connect(url.render_as_string(hide_password=False), connect_timeout=2) as conn:
            conn.execute("set local statement_timeout='3000ms'")
            row = conn.execute(
                "select rolsuper,rolcreaterole,rolcreatedb,rolbypassrls from pg_roles "
                "where rolname=%s",
                (ROLE,),
            ).fetchone()
            if row and any(row):
                raise HTTPException(409, "Role SQL reader hiện có quyền vượt mức; cần kiểm tra.")
            role = sql.Identifier(ROLE)
            if row is None:
                conn.execute(sql.SQL("create role {} login noinherit").format(role))
            conn.execute(
                sql.SQL(
                    "alter role {} nosuperuser nocreatedb nocreaterole noreplication "
                    "nobypassrls noinherit connection limit 4 password {}"
                ).format(role, sql.Literal(password))
            )
            conn.execute(
                sql.SQL("grant connect on database {} to {}").format(
                    sql.Identifier(str(url.database)), role
                )
            )
            schemas = conn.execute(
                "select nspname from pg_namespace where nspname=any(%s)", (list(SCHEMAS),)
            ).fetchall()
            for (name,) in schemas:
                schema = sql.Identifier(name)
                conn.execute(sql.SQL("grant usage on schema {} to {}").format(schema, role))
                conn.execute(
                    sql.SQL("grant select on all tables in schema {} to {}").format(schema, role)
                )
                conn.execute(
                    sql.SQL(
                        "alter default privileges for role {} in schema {} "
                        "grant select on tables to {}"
                    ).format(sql.Identifier(str(url.username)), schema, role)
                )
        prepared[database] = time.monotonic()
        return password


@contextmanager
def reader(database: Database) -> Iterator[psycopg.Connection[Any]]:
    url = local_url(database)
    password = provision(database, url)
    with psycopg.connect(
        url.set(username=ROLE, password=password).render_as_string(hide_password=False),
        connect_timeout=2,
        options=(
            "-c statement_timeout=5000 -c lock_timeout=800 "
            "-c default_transaction_read_only=on -c work_mem=4096 "
            "-c idle_in_transaction_session_timeout=6000"
        ),
    ) as conn:
        yield conn


@router.get("/{database}/catalog")
def catalog(database: Database) -> dict[str, Any]:
    try:
        with reader(database) as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """select table_schema as schema,table_name as name,table_type as kind
                from information_schema.tables where table_schema=any(%s)
                order by table_schema,table_name""",
                (list(SCHEMAS),),
            )
            tables = cursor.fetchall()
            cursor.execute(
                """select c.table_schema as schema,c.table_name as table,
                c.column_name as name,c.data_type as type,c.is_nullable as nullable,
                c.column_default as default,c.ordinal_position as position,
                exists(select 1 from pg_index i join pg_class t on t.oid=i.indrelid
                  join pg_namespace n on n.oid=t.relnamespace
                  join pg_attribute a on a.attrelid=t.oid and a.attnum=any(i.indkey)
                  where i.indisprimary and n.nspname=c.table_schema
                  and t.relname=c.table_name and a.attname=c.column_name) as primary_key
                from information_schema.columns c where c.table_schema=any(%s)
                order by c.table_schema,c.table_name,c.ordinal_position""",
                (list(SCHEMAS),),
            )
            columns = cursor.fetchall()
        return {"database": database, "tables": tables, "columns": columns}
    except psycopg.Error as error:
        raise HTTPException(503, "Không đọc được schema. Kiểm tra dịch vụ PostgreSQL.") from error


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str = Field(min_length=1, max_length=20_000)
    limit: int = Field(default=100, ge=1, le=500, strict=True)


def bounded_query(statement: str) -> sql.Composed:
    # Extended-query parameters reject multiple statements; a subquery accepts SELECT/WITH
    # but not transaction commands or a data-modifying top-level WITH.
    statement = statement.strip().removesuffix(";")
    return sql.SQL("select * from (\n{}\n) as routeflow_result limit %s").format(sql.SQL(statement))


def collect(cursor: Any, limit: int) -> dict[str, Any]:
    columns = [column.name for column in cursor.description or []]
    if len(columns) > 80:
        raise HTTPException(422, "Chọn tối đa 80 cột cho một truy vấn.")
    rows: list[list[Any]] = []
    clipped = truncated = False
    size = 0
    for index in range(limit + 1):
        record = cursor.fetchone()
        if record is None:
            break
        if index == limit:
            truncated = True
            break
        cells: list[Any] = []
        for value in record:
            if value is None or isinstance(value, (bool, int, float)):
                cells.append(value)
            else:
                text = (
                    json.dumps(value, ensure_ascii=False, default=str)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                clipped |= len(text) > 2000
                cells.append(text[:2000] + ("…" if len(text) > 2000 else ""))
        size += len(json.dumps(cells, ensure_ascii=False, default=str).encode())
        if size > 1_000_000:
            clipped = truncated = True
            break
        rows.append(cells)
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "clipped": clipped,
        "limit": limit,
    }


@router.post("/{database}/query")
def query(database: Database, body: Query) -> dict[str, Any]:
    if not query_slots.acquire(blocking=False):
        raise HTTPException(429, "Đang chạy hai truy vấn. Đợi một truy vấn hoàn tất.")
    started = time.monotonic()
    try:
        with reader(database) as conn:
            watchdog = threading.Timer(6, conn.cancel)
            watchdog.daemon = True
            watchdog.start()
            try:
                # ServerCursor forces the extended protocol and streams rows; large results
                # aren't buffered into the console before the response-size bound is applied.
                with conn.cursor(name="routeflow_query") as cursor:
                    cursor.execute(bounded_query(body.sql), (body.limit + 1,))
                    result = collect(cursor, body.limit)
            finally:
                watchdog.cancel()
        return {
            "database": database,
            **result,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
    except psycopg.errors.QueryCanceled as error:
        raise HTTPException(408, "Truy vấn vượt thời gian cho phép (5 giây).") from error
    except psycopg.Error as error:
        message = error.diag.message_primary or "Không thực hiện được truy vấn."
        raise HTTPException(422, "SQL: " + message[:500]) from error
    finally:
        query_slots.release()
