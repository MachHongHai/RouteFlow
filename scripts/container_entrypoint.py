"""Wait for dependencies even when Docker Desktop starts existing containers concurrently."""

import os
import sys
import time
import urllib.request

import psycopg
from sqlalchemy.engine import make_url


def wait() -> None:
    mode = os.environ.get("ROUTEFLOW_WAIT_MODE")
    if mode not in {"app", "init"}:
        return  # Cloud images and one-off commands keep their existing startup behavior.
    initializing = mode == "init"
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        try:
            for key in ("SOURCE_DATABASE_URL", "WAREHOUSE_DATABASE_URL"):
                url = make_url(os.environ[key]).set(drivername="postgresql")
                with psycopg.connect(
                    url.render_as_string(hide_password=False), connect_timeout=2
                ) as connection:
                    connection.execute("select 1")
                    if not initializing:
                        table = "outbox_events" if key == "SOURCE_DATABASE_URL" else "raw_events"
                        if (
                            connection.execute("select to_regclass(%s)", (table,)).fetchone()[0]
                            is None
                        ):
                            raise RuntimeError("Waiting for migration")
            host = os.environ["PUBSUB_EMULATOR_HOST"]
            project = os.environ["GOOGLE_CLOUD_PROJECT"]
            path = (
                "/"
                if initializing
                else f"/v1/projects/{project}/subscriptions/delivery-events-local"
            )
            with urllib.request.urlopen(f"http://{host}{path}", timeout=2):
                pass
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Dependencies not ready after 150 seconds; inspect init/database logs.")


if __name__ == "__main__":
    wait()
    os.execvp(sys.argv[1], sys.argv[1:])
