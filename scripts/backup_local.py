"""Quiesced local backups and restore drills into disposable, network-isolated PostgreSQL."""

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POSTGRES = "postgres:16@sha256:1a6ab3f5345eb6dbe04a1349529caabdb0ab09293a09590fad07b2246bfa4b54"
DATABASES = {"source": "routeflow", "warehouse": "warehouse"}
VOLUMES = {"archive": "routeflow_archive", "lake": "routeflow_lake"}


def docker(*arguments: str) -> str:
    return subprocess.run(
        ["docker", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def query(container: str, database: str, sql: str) -> str:
    return docker(
        "exec",
        container,
        "psql",
        "-X",
        "-U",
        "routeflow",
        "-d",
        database,
        "-At",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    )


def fingerprints(container: str, database: str) -> list[dict[str, Any]]:
    names = query(
        container,
        database,
        """
        select quote_ident(table_schema)||'.'||quote_ident(table_name)
        from information_schema.tables
        where table_type='BASE TABLE'
          and table_schema in ('public','analytics','staging','intermediate')
        order by table_schema,table_name
    """,
    ).splitlines()
    statements = []
    for name in names:
        label = name.replace("'", "''")
        statements.append(f"""
            select json_build_object('table','{label}','rows',count(*),'digest',
              md5(coalesce(string_agg(md5(row_to_json(t)::text),''
                  order by md5(row_to_json(t)::text)),'')))::text
            from {name} t
        """)
    if not statements:
        raise RuntimeError("No RouteFlow tables found; refusing to call this a valid backup")
    return [
        json.loads(line) for line in query(container, database, ";".join(statements)).splitlines()
    ]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def backup(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    if docker(
        "ps",
        "-q",
        "--filter",
        "label=com.docker.compose.project=routeflow",
        "--filter",
        "label=com.docker.compose.service=spark-job",
    ):
        raise RuntimeError("Wait for the Spark job to finish before backing up")
    running = set(docker("compose", "ps", "--status", "running", "--services").splitlines())
    if not {"source", "warehouse", "api", "consumer", "relay"} <= running:
        raise RuntimeError("Start the full local core stack before a quiesced backup")
    containers = {service: docker("compose", "ps", "-q", service) for service in DATABASES}
    for volume in VOLUMES.values():
        docker("volume", "inspect", volume)
    paused: list[str] = []
    try:
        docker("compose", "stop", "api")
        paused.append("api")
        # Drain the source outbox into RAW before stopping the ingestion workers.
        docker(
            "compose", "exec", "-T", "consumer", "python", "-m", "routeflow.cli", "wait-ingestion"
        )
        docker("compose", "stop", "relay", "consumer")
        paused.extend(["relay", "consumer"])
        before = {name: fingerprints(containers[name], db) for name, db in DATABASES.items()}
        files: dict[str, dict[str, Any]] = {}
        for name, database in DATABASES.items():
            docker(
                "exec",
                containers[name],
                "pg_dump",
                "-U",
                "routeflow",
                "-d",
                database,
                "-Fc",
                "-f",
                "/tmp/routeflow-backup.dump",
            )
            filename = name + ".dump"
            docker(
                "cp", containers[name] + ":/tmp/routeflow-backup.dump", str(destination / filename)
            )
            files[filename] = {
                "bytes": (destination / filename).stat().st_size,
                "sha256": sha256(destination / filename),
            }
        for name, volume in VOLUMES.items():
            filename = name + ".tar.gz"
            docker(
                "run",
                "--rm",
                "--pull=never",
                "--network",
                "none",
                "--user",
                "root",
                "--mount",
                f"type=volume,source={volume},target=/data,readonly",
                "--mount",
                f"type=bind,source={destination},target=/backup",
                "--entrypoint",
                "tar",
                "routeflow-app:local",
                "-czf",
                "/backup/" + filename,
                "-C",
                "/data",
                ".",
            )
            files[filename] = {
                "bytes": (destination / filename).stat().st_size,
                "sha256": sha256(destination / filename),
            }
        after = {name: fingerprints(containers[name], db) for name, db in DATABASES.items()}
        if before != after:
            raise RuntimeError("Database contents changed during backup; backup not accepted")
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "postgres_image": POSTGRES,
            "tables": before,
            "files": files,
            "restore_verified": False,
        }
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps({"backup": str(destination), "files": files}, indent=2))
    finally:
        if paused:
            docker("compose", "start", *paused)


def verify(destination: Path) -> None:
    import tarfile

    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    expected_files = {"source.dump", "warehouse.dump", "archive.tar.gz", "lake.tar.gz"}
    if manifest.get("format") != 1 or set(manifest["files"]) != expected_files:
        raise RuntimeError("Unsupported backup manifest")
    for filename in expected_files:
        path = destination / filename
        expected = manifest["files"][filename]
        if path.stat().st_size != expected["bytes"] or sha256(path) != expected["sha256"]:
            raise RuntimeError(f"Backup integrity failed: {filename}")
    result: dict[str, Any] = {"checked_at": datetime.now(UTC).isoformat(), "databases": {}}
    for service in DATABASES:
        name = "routeflow-restore-check-" + service + "-" + uuid.uuid4().hex[:10]
        docker(
            "run",
            "--rm",
            "-d",
            "--pull=never",
            "--name",
            name,
            "--network",
            "none",
            "--memory",
            "512m",
            "--tmpfs",
            "/var/lib/postgresql/data:rw,size=256m",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_USER=routeflow",
            "-e",
            "POSTGRES_DB=restore_check",
            POSTGRES,
        )
        try:
            for _ in range(60):
                ready = subprocess.run(
                    [
                        "docker",
                        "exec",
                        name,
                        "pg_isready",
                        "-U",
                        "routeflow",
                        "-d",
                        "restore_check",
                    ],
                    capture_output=True,
                    check=False,
                )
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise TimeoutError("Restore-check PostgreSQL did not start")
            docker("cp", str(destination / (service + ".dump")), name + ":/tmp/backup.dump")
            docker(
                "exec",
                name,
                "pg_restore",
                "-U",
                "routeflow",
                "-d",
                "restore_check",
                "--exit-on-error",
                "--no-owner",
                "/tmp/backup.dump",
            )
            actual = fingerprints(name, "restore_check")
            if actual != manifest["tables"][service]:
                raise RuntimeError(f"Restored table contents differ: {service}")
            result["databases"][service] = {
                "tables": len(actual),
                "all_row_fingerprints_match": True,
            }
        finally:
            subprocess.run(["docker", "stop", name], capture_output=True, check=False)
    # Exercise safe extraction into a new D directory, independent of Docker's original volumes.
    extracted = destination / ("restore-check-" + uuid.uuid4().hex[:10])
    extracted.mkdir()
    result["archives"] = {}
    for filename in ("archive.tar.gz", "lake.tar.gz"):
        target = extracted / filename.removesuffix(".tar.gz")
        target.mkdir()
        with tarfile.open(destination / filename) as archive:
            archive.extractall(target, filter="data")
        result["archives"][filename] = {
            "extracted_files": sum(path.is_file() for path in target.rglob("*"))
        }
    result["restore_verified"] = True
    (destination / "restore-verification.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "verify"])
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.resolve()
    if os.name == "nt" and destination.drive.upper() != "D:":
        raise ValueError("Keep logical backups and restore-check outputs on D on this workstation")
    if args.action == "backup":
        backup(destination)
    else:
        verify(destination)


if __name__ == "__main__":
    main()
