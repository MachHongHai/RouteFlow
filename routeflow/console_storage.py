"""Docker-volume policy and optional D/E workstation storage checks."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

CONTAINER_MODE = os.environ.get("ROUTEFLOW_CONSOLE_CONTAINER") == "1"


def storage_ready(snapshot: dict[str, Any]) -> bool:
    return snapshot.get("controls_allowed", snapshot.get("pinned_to_e")) is True


def storage_summary() -> dict[str, Any]:
    if CONTAINER_MODE and os.getenv("ROUTEFLOW_CONSOLE_STORAGE_POLICY") == "docker-volume":
        return {
            "policy": "docker-volume",
            "controls_allowed": True,
            "pinned_to_e": None,
            "disks": [],
            "docker_path": "Docker managed volumes",
            "docker_bytes": None,
        }
    try:
        snapshot = workstation_storage_summary()
        workstation = CONTAINER_MODE or os.name == "nt"
        snapshot["policy"] = "workstation" if workstation else "docker-volume"
        snapshot["controls_allowed"] = snapshot["pinned_to_e"] is True if workstation else True
        return snapshot
    except (OSError, ValueError, KeyError):
        return {
            "policy": "workstation",
            "controls_allowed": False,
            "pinned_to_e": False,
            "disks": [],
            "docker_path": None,
            "docker_bytes": None,
        }


def workstation_storage_summary() -> dict[str, Any]:
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
