"""Keep the web process unprivileged; only the fixed-operation broker owns the socket."""

import os
import subprocess
import sys


def main() -> None:
    subprocess.Popen([sys.executable, "-m", "routeflow.console_broker"])
    os.setgroups([])  # type: ignore[attr-defined]  # Linux container only.
    os.setgid(10001)  # type: ignore[attr-defined]
    os.setuid(10001)  # type: ignore[attr-defined]
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "routeflow.console:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
            "--no-proxy-headers",
            "--no-access-log",
        ],
    )


if __name__ == "__main__":
    main()
