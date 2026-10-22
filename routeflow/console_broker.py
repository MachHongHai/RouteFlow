"""Private loopback broker: fixed Docker operations, never an Engine API proxy."""

import http.client
import json
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlencode

MANAGED = (
    "source",
    "warehouse",
    "pubsub",
    "api",
    "relay",
    "consumer",
    "spark-master",
    "spark-worker",
)
APPS = {"api", "relay", "consumer"}
LOCK = threading.Lock()


class EngineConnection(http.client.HTTPConnection):
    def __init__(self) -> None:
        super().__init__("localhost", timeout=35)

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # type: ignore[attr-defined]
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


def engine(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    connection = EngineConnection()
    try:
        connection.request(
            method,
            "/v1.51" + path,
            body=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        response = connection.getresponse()
        content = response.read(2_000_000)
        if response.status not in {200, 201, 204, 304}:
            raise RuntimeError(f"Docker trả về HTTP {response.status}; kiểm tra log dịch vụ.")
        if "application/json" in response.getheader("Content-Type", ""):
            return json.loads(content) if content else {}
        return content
    finally:
        connection.close()


def container(service: str) -> dict[str, Any]:
    if service not in {*MANAGED, "init"}:
        raise ValueError("Dịch vụ không nằm trong RouteFlow.")
    record: dict[str, Any] = engine("GET", f"/containers/routeflow-{service}-1/json")
    labels = record.get("Config", {}).get("Labels", {})
    if (
        labels.get("com.docker.compose.project") != "routeflow"
        or labels.get("com.docker.compose.service") != service
    ):
        raise ValueError("Container không có nhãn RouteFlow hợp lệ.")
    return record


def wait_ready(service: str, deadline: float) -> None:
    while time.monotonic() < deadline:
        state = container(service)["State"]
        if service == "init":
            if not state["Running"]:
                if state["ExitCode"]:
                    raise RuntimeError("Init thất bại. Kiểm tra log trong Docker Desktop.")
                return
        elif state["Running"] and state.get("Health", {}).get("Status", "healthy") == "healthy":
            return
        time.sleep(1)
    raise TimeoutError("Quá thời gian chờ; làm mới để kiểm tra trạng thái dịch vụ.")


def start_services(target: str) -> None:
    deadline = time.monotonic() + 140
    selected = set(MANAGED) if target == "stack" else {target}
    needs_app = bool(selected & APPS)
    provision = needs_app and not container("pubsub")["State"]["Running"]
    if needs_app:
        selected.update({"source", "warehouse", "pubsub"})
    if "spark-worker" in selected:
        selected.add("spark-master")
    for service in MANAGED:
        if service not in selected:
            continue
        if service in APPS:
            init = container("init")
            if provision or init["State"]["ExitCode"] != 0 or init["State"]["Running"]:
                if not init["State"]["Running"]:
                    engine("POST", f"/containers/{init['Id']}/start")
                wait_ready("init", deadline)
                provision = False
        record = container(service)
        if not record["State"]["Running"]:
            engine("POST", f"/containers/{record['Id']}/start")
        wait_ready(service, deadline)


def operate(target: str, action: str) -> str:
    if target not in {*MANAGED, "stack"} or action not in {"start", "stop", "restart"}:
        raise ValueError("Thao tác không được hỗ trợ.")
    if not LOCK.acquire(blocking=False):
        raise RuntimeError("Đang xử lý thao tác khác.")
    try:
        if action == "start":
            start_services(target)
        elif action == "restart" and target == "stack":
            for service in reversed(MANAGED):
                record = container(service)
                engine("POST", f"/containers/{record['Id']}/stop?t=10")
            start_services(target)
        else:
            selected = reversed(MANAGED) if target == "stack" else (target,)
            for service in selected:
                record = container(service)
                engine("POST", f"/containers/{record['Id']}/{action}?t=10")
        return "Đã hoàn tất thao tác; UI vẫn hoạt động."
    finally:
        LOCK.release()


def demultiplex(content: bytes) -> str:
    output = bytearray()
    position = 0
    while position + 8 <= len(content) and content[position : position + 4] in {
        b"\x01\x00\x00\x00",
        b"\x02\x00\x00\x00",
    }:
        length = struct.unpack(">I", content[position + 4 : position + 8])[0]
        output.extend(content[position + 8 : position + 8 + length])
        position += 8 + length
    return (bytes(output) if position else content)[-200_000:].decode("utf-8", errors="replace")


def run_dbt() -> dict[str, Any]:
    """One fixed command in the existing API container; callers cannot supply argv/env."""
    if not LOCK.acquire(blocking=False):
        raise RuntimeError("Đang xử lý thao tác khác.")
    try:
        record = container("api")
        if not record["State"]["Running"]:
            raise RuntimeError("Delivery API đang dừng.")
        execution = engine(
            "POST",
            f"/containers/{record['Id']}/exec",
            {
                "Cmd": ["python", "-m", "routeflow.cli", "dbt"],
                "User": "10001",
                "WorkingDir": "/app",
                "AttachStdout": False,
                "AttachStderr": False,
            },
        )
        identifier = execution["Id"]
        engine("POST", f"/exec/{identifier}/start", {"Detach": True, "Tty": False})
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            result = engine("GET", f"/exec/{identifier}/json")
            if not result["Running"]:
                if result["ExitCode"] != 0:
                    raise RuntimeError(
                        "dbt thất bại. Xem lịch sử pipeline và /app/dbt/logs/dbt.log."
                    )
                return {"exit_code": 0}
            time.sleep(1)
        raise TimeoutError(
            "dbt chưa kết thúc trong 240 giây; tiến trình có thể vẫn chạy trong API."
        )
    finally:
        LOCK.release()


def dispatch(method: str, path: str, body: dict[str, Any]) -> Any:
    if method == "POST" and path == "/workloads/dbt":
        if body:
            raise ValueError("dbt không nhận tham số tùy ý.")
        return run_dbt()
    if method == "GET" and path == "/version":
        return {"version": engine("GET", "/version")["Version"]}
    if method == "GET" and path == "/containers":
        filters = urlencode(
            {"all": "1", "filters": json.dumps({"label": ["com.docker.compose.project=routeflow"]})}
        )
        return [
            {
                "Names": record["Names"][0].lstrip("/"),
                "State": record["State"],
                "Status": record["Status"],
                "Ports": ", ".join(
                    f"{port.get('IP', '')}:{port['PublicPort']} → {port['PrivatePort']}"
                    for port in (record.get("Ports") or [])
                    if "PublicPort" in port
                ),
            }
            for record in engine("GET", "/containers/json?" + filters)
        ]
    if method == "GET" and path.startswith("/logs/"):
        service = path.removeprefix("/logs/")
        if service not in MANAGED:
            raise ValueError("Dịch vụ không được hỗ trợ.")
        record = container(service)
        content = engine("GET", f"/containers/{record['Id']}/logs?stdout=1&stderr=1&tail=150")
        return {"content": demultiplex(content)}
    if method == "POST" and path.startswith("/actions/"):
        return {"output": operate(path.removeprefix("/actions/"), body.get("action", ""))}
    raise ValueError("Đường dẫn không được hỗ trợ.")


class Handler(BaseHTTPRequestHandler):
    def respond(self, status: int, payload: Any) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        try:
            self.respond(200, dispatch("GET", self.path, {}))
        except ValueError as error:
            self.respond(400, {"detail": str(error)})
        except Exception:
            self.respond(503, {"detail": "Không đọc được trạng thái Docker."})

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 200:
                raise ValueError("Yêu cầu không hợp lệ.")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Yêu cầu không hợp lệ.")
            self.respond(200, dispatch("POST", self.path, body))
        except ValueError as error:
            self.respond(400, {"detail": str(error)})
        except Exception:
            self.respond(503, {"detail": "Không hoàn tất thao tác. Kiểm tra trạng thái/log."})

    def log_message(self, format: str, *args: Any) -> None:
        pass


def main() -> None:
    ThreadingHTTPServer(("127.0.0.1", 58100), Handler).serve_forever()


if __name__ == "__main__":
    main()
