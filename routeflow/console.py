"""Loopback-only control panel, independent of the Docker-hosted business API."""

import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.request import Request as URLRequest
from urllib.request import urlopen

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from pydantic import BaseModel
from sqlalchemy.engine import make_url

from routeflow.config import settings

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).parent / "console_assets"
TOKEN = secrets.token_urlsafe(32)
CONTAINER_MODE = os.environ.get("ROUTEFLOW_CONSOLE_CONTAINER") == "1"
SERVICES: dict[str, dict[str, Any]] = {
    "source": {
        "name": "Source PostgreSQL",
        "kind": "database",
        "port": 55432,
        "detail": "Đơn hàng, thanh toán và transactional outbox",
        "icon": "database",
    },
    "warehouse": {
        "name": "Analytics Warehouse",
        "kind": "database",
        "port": 55433,
        "detail": "RAW events, dbt marts và dữ liệu GPS",
        "icon": "layers",
    },
    "pubsub": {
        "name": "Pub/Sub Emulator",
        "kind": "streaming",
        "port": 58085,
        "detail": "Chuyển sự kiện giữa ứng dụng và consumer",
        "icon": "route",
    },
    "api": {
        "name": "Delivery API",
        "kind": "application",
        "port": 58000,
        "detail": "FastAPI · nghiệp vụ giao hàng",
        "icon": "code",
        "url": "http://localhost:58000/docs",
    },
    "relay": {
        "name": "Outbox Relay",
        "kind": "streaming",
        "port": None,
        "detail": "Đọc outbox, publish và retry có kiểm soát",
        "icon": "route",
    },
    "consumer": {
        "name": "Event Consumer",
        "kind": "streaming",
        "port": None,
        "detail": "Kiểm tra contract, archive và ghi RAW",
        "icon": "inbox",
    },
    "spark-master": {
        "name": "Spark Master",
        "kind": "processing",
        "port": 58080,
        "detail": "Điều phối batch GPS · Spark 4.0.2",
        "icon": "spark",
        "url": "http://localhost:58080",
    },
    "spark-worker": {
        "name": "Spark Worker",
        "kind": "processing",
        "port": None,
        "detail": "2 cores · bộ nhớ executor 1,5 GiB",
        "icon": "cpu",
    },
}
TABLES = {
    "orders": ("source", "public.orders", "Đơn hàng", "created_at desc, id"),
    "outbox": (
        "source",
        "public.outbox_events",
        "Transactional outbox",
        "created_at desc, event_id",
    ),
    "runs": ("source", "public.pipeline_runs", "Lịch sử pipeline", "created_at desc, id"),
    "dlq": ("source", "public.dead_letters", "Dead-letter queue", "created_at desc, id"),
    "facts": ("warehouse", "analytics.fact_order", "Order mart", "created_at desc, order_id"),
    "gps": (
        "warehouse",
        "staging.stg_driver_gps_daily",
        "GPS theo ngày",
        "business_date desc, driver_id",
    ),
    "raw": ("warehouse", "public.raw_events", "RAW events", "ingested_at desc, event_id"),
}
app = FastAPI(title="RouteFlow Console", docs_url=None, redoc_url=None, openapi_url=None)
pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="routeflow-console")
job_lock = threading.Lock()
jobs: dict[str, dict[str, Any]] = {}


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def redact(value: str) -> str:
    value = re.sub(r"(\w+://[^\s/:]+:)[^\s@]+@", r"\1***@", value)
    return re.sub(
        r"(?i)(authorization[:=]\s*bearer\s+|(?:password|token|api_key)[=:]\s*)\S+", r"\1***", value
    )


def execute(arguments: list[str], timeout: int = 12) -> str:
    if CONTAINER_MODE and arguments[0] == "console-broker":
        result = broker(f"/actions/{arguments[1]}", {"action": arguments[2]}, timeout=timeout)
        return redact(result["output"])
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise RuntimeError(redact((result.stderr or result.stdout)[-3000:]))
    return redact(result.stdout[-200_000:])


def docker(*arguments: str, timeout: int = 12) -> str:
    if CONTAINER_MODE:
        if arguments[0] == "version":
            return str(broker("/version", timeout=timeout)["version"])
        if arguments[0] == "ps":
            return "\n".join(json.dumps(row) for row in broker("/containers", timeout=timeout))
        if arguments[:2] == ("compose", "logs") and arguments[-1] in SERVICES:
            return redact(broker(f"/logs/{arguments[-1]}", timeout=timeout)["content"])
        raise ValueError("Lệnh Docker không được hỗ trợ trong console.")
    return execute(["docker", *arguments], timeout)


def broker(path: str, body: dict[str, str] | None = None, timeout: int = 12) -> Any:
    request = URLRequest(
        "http://127.0.0.1:58100" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(json.load(error).get("detail", "Không kết nối được broker.")) from error


def guarded(arguments: list[str], desktop: bool = False) -> list[str]:
    if os.name != "nt":
        return ["docker", *arguments]
    powershell = shutil.which("pwsh") or "powershell.exe"
    script = ROOT / "scripts" / ("start-docker.ps1" if desktop else "dev.ps1")
    return [
        powershell,
        "-NoProfile",
        "-File",
        str(script),
        *([] if desktop else ["docker", *arguments]),
    ]


@app.middleware("http")
async def local_only(request: Request, call_next: Any) -> Any:
    client = request.client.host if request.client else ""
    allowed_client = client in {"127.0.0.1", "::1"}
    if CONTAINER_MODE and client:
        try:
            allowed_client = ipaddress.ip_address(client).is_private
        except ValueError:
            pass
    if (
        request.client is None
        or not allowed_client
        or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}
    ):
        return JSONResponse({"detail": "Console chỉ mở trên localhost."}, status_code=403)
    if request.method not in {"GET", "HEAD"}:
        origin = request.headers.get("origin")
        if (origin and origin != str(request.base_url).rstrip("/")) or not hmac.compare_digest(
            request.headers.get("x-console-token", ""), TOKEN
        ):
            return JSONResponse(
                {"detail": "Phiên đã hết hạn. Tải lại trang để tiếp tục."}, status_code=403
            )
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    return response


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (ASSETS / "index.html").read_text(encoding="utf-8").replace("__CONSOLE_TOKEN__", TOKEN)


app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")


def read_sql(database: str, query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cfg = settings()
    if cfg.environment != "local" or cfg.warehouse_mode != "postgres":
        raise RuntimeError("Console hỗ trợ database local.")
    url = make_url(cfg.source_database_url if database == "source" else cfg.warehouse_database_url)
    allowed_hosts = (
        {"source" if database == "source" else "warehouse"}
        if CONTAINER_MODE
        else {"127.0.0.1", "localhost", "::1"}
    )
    if url.host not in allowed_hosts:
        raise RuntimeError("Database phải nằm trên localhost.")
    with psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        connect_timeout=2,
        options="-c statement_timeout=2500 -c default_transaction_read_only=on",
        row_factory=dict_row,
    ) as connection:
        return list(connection.execute(query, parameters).fetchall())


def data_summary() -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": None,
        "warehouse": None,
        "issues": [],
    }
    try:
        result["source"] = read_sql(
            "source",
            """select
            (select count(*) from orders) as orders,
            (select count(*) from outbox_events where published_at is null) as pending,
            (select count(*) from dead_letters where resolved_at is null) as dlq""",
        )[0]
    except Exception:
        result["issues"].append("Chưa đọc được database nguồn. Kiểm tra Source PostgreSQL.")
    try:
        result["warehouse"] = read_sql(
            "warehouse",
            """select
            (select count(*) from raw_events) as events,
            (select count(*) from analytics.fact_order) as facts,
            (select coalesce(sum(gps_points),0) from staging.stg_driver_gps_daily) as gps_points,
            (select coalesce(sum(estimated_distance_km),0)
                from staging.stg_driver_gps_daily) as gps_km""",
        )[0]
    except Exception:
        result["issues"].append("Warehouse đang dừng hoặc marts chưa được tạo.")
    return result


def storage_summary() -> dict[str, Any]:
    if CONTAINER_MODE:
        snapshot = json.loads(Path("/host/console/host.json").read_text(encoding="utf-8-sig"))
        config = json.loads(
            Path("/host/docker-settings/settings-store.json").read_text(encoding="utf-8-sig")
        )
        snapshot["pinned_to_e"] = config.get("CustomWslDistroDir") == "E:\\DockerDesktop\\data\\wsl"
        mounts = {
            "C:": "/host/docker-settings",
            "D:": "/host/console",
            "E:": "/host/docker-storage",
        }
        for disk in snapshot["disks"]:
            usage = shutil.disk_usage(mounts[disk["drive"]])
            if abs(usage.total - disk["total"]) < 1024 * 1024:
                disk.update(total=usage.total, used=usage.used, free=usage.free)
            else:
                snapshot["disk_snapshot_at"] = snapshot["observed_at"]
        return snapshot
    disks = []
    for drive in ("C:/", "D:/", "E:/"):
        if Path(drive).exists():
            usage = shutil.disk_usage(drive)
            disks.append(
                {"drive": drive[:2], "total": usage.total, "used": usage.used, "free": usage.free}
            )
    vhd = Path("E:/DockerDesktop/data/wsl/disk/docker_data.vhdx")
    proof_path = Path(
        "D:/RouteFlow-backups/recovered-after-docker-update-20261016/restore-verification.json"
    )
    backup: dict[str, Any] | None = None
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8-sig"))
        backup = {
            "verified": proof.get("restore_verified") is True,
            "checked_at": proof.get("checked_at"),
            "path": str(proof_path.parent),
        }
    except (OSError, ValueError):
        pass
    pinned: bool | None = None
    if os.name == "nt":
        try:
            config = json.loads(
                (Path(os.environ["APPDATA"]) / "Docker/settings-store.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            pinned = config.get("CustomWslDistroDir") == "E:\\DockerDesktop\\data\\wsl"
        except (OSError, ValueError, KeyError):
            pinned = False
    return {
        "disks": disks,
        "docker_bytes": vhd.stat().st_size if vhd.is_file() else None,
        "docker_path": str(vhd),
        "pinned_to_e": pinned,
        "backup": backup,
    }


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    services = [
        {"id": key, **value, "state": "unknown", "status": "Chưa kết nối Docker"}
        for key, value in SERVICES.items()
    ]
    engine: dict[str, Any] = {"available": False, "version": None}
    try:
        version = docker("version", "--format", "{{.Server.Version}}", timeout=5).strip()
        records = [
            json.loads(line)
            for line in docker(
                "ps",
                "-a",
                "--filter",
                "label=com.docker.compose.project=routeflow",
                "--format",
                "{{json .}}",
            ).splitlines()
            if line
        ]
        for service in services:
            name = f"routeflow-{service['id']}-1"
            container = next((row for row in records if row["Names"] == name), None)
            service.update(
                state=container.get("State", "unknown") if container else "missing",
                status=container.get("Status", "") if container else "Chưa được tạo",
            )
        engine = {"available": True, "version": version}
    except Exception:
        engine["message"] = "Chưa kết nối Docker Desktop. Bạn có thể mở Docker từ bảng điều khiển."
    return {
        "checked_at": timestamp(),
        "docker": engine,
        "services": services,
        "data": data_summary(),
        "storage": storage_summary(),
    }


@app.get("/api/tables")
def tables() -> list[dict[str, str]]:
    return [{"id": key, "database": value[0], "name": value[2]} for key, value in TABLES.items()]


@app.get("/api/tables/{table_id}")
def table_rows(table_id: str, page: int = Query(1, ge=1, le=10000)) -> dict[str, Any]:
    if table_id not in TABLES:
        raise HTTPException(404, "Bảng không nằm trong danh sách cho phép.")
    database, table, name, order = TABLES[table_id]
    try:
        total = read_sql(database, f"select count(*) as count from {table}")[0]["count"]
        rows = read_sql(
            database,
            f"select * from {table} order by {order} limit 20 offset %s",
            ((page - 1) * 20,),
        )
        return {"name": name, "page": page, "total": total, "rows": rows}
    except Exception as error:
        raise HTTPException(
            503, "Chưa đọc được bảng. Hãy bật database và kiểm tra migration/dbt."
        ) from error


@app.get("/api/logs/{service}")
def logs(service: str) -> dict[str, str]:
    if service not in SERVICES:
        raise HTTPException(404, "Dịch vụ không được hỗ trợ.")
    try:
        output = docker("compose", "logs", "--no-color", "--tail", "150", service)
        return {"service": service, "content": output or "Chưa có log cho dịch vụ này."}
    except Exception as error:
        raise HTTPException(503, "Chưa đọc được log. Kiểm tra Docker Desktop.") from error


class Action(BaseModel):
    action: Literal["start", "stop", "restart"]


def action_command(target: str, action: str) -> list[str]:
    if CONTAINER_MODE:
        if target not in {*SERVICES, "stack"}:
            raise HTTPException(404, "Dịch vụ không nằm trong RouteFlow.")
        if storage_summary()["pinned_to_e"] is not True:
            raise HTTPException(409, "Cấu hình Docker không còn trỏ đến E. Dừng để kiểm tra.")
        return ["console-broker", target, action]
    if target == "docker" and action == "start":
        return guarded([], desktop=True)
    if target not in SERVICES and target != "stack":
        raise HTTPException(404, "Dịch vụ không nằm trong RouteFlow.")
    prefix = ["compose", "--profile", "spark"]
    if action == "start":
        arguments = [*prefix, "up", "-d", "--no-build", "--pull", "never"]
    else:
        arguments = [*prefix, action]
    arguments.extend(SERVICES if target == "stack" else [target])
    return guarded(arguments)


def perform(identifier: str, command: list[str]) -> None:
    try:
        output = execute(command, timeout=180)
        with job_lock:
            jobs[identifier].update(
                status="success", output=output[-6000:], finished_at=timestamp()
            )
    except Exception as error:
        message = (
            "Thao tác quá thời gian chờ; hãy làm mới để kiểm tra trạng thái."
            if isinstance(error, subprocess.TimeoutExpired)
            else redact(str(error))[-3000:]
        )
        with job_lock:
            jobs[identifier].update(status="failed", output=message, finished_at=timestamp())


@app.post("/api/actions/{target}", status_code=202)
def action(target: str, body: Action) -> dict[str, Any]:
    command = action_command(target, body.action)
    with job_lock:
        if any(job["status"] == "running" for job in jobs.values()):
            raise HTTPException(409, "Đang xử lý một thao tác khác. Vui lòng đợi hoàn tất.")
        identifier = secrets.token_hex(8)
        job = {
            "id": identifier,
            "target": target,
            "action": body.action,
            "status": "running",
            "started_at": timestamp(),
            "output": "",
        }
        if len(jobs) >= 20:
            del jobs[next(iter(jobs))]
        jobs[identifier] = job
    pool.submit(perform, identifier, command)
    return job.copy()


@app.get("/api/jobs/{identifier}")
def job_status(identifier: str) -> dict[str, Any]:
    with job_lock:
        if identifier not in jobs:
            raise HTTPException(404, "Không tìm thấy thao tác.")
        return jobs[identifier].copy()
