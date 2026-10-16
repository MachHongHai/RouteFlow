# Storage placement on this Windows workstation

The source repository and its `.venv`, test artifacts, dbt outputs and host caches stay on D.
Docker Desktop's bulk storage belongs on E, as requested by the owner. Do not run more image
builds unless the storage checks in the development wrapper pass.

| Data | Physical location |
|---|---|
| Repository and project virtual environment | `D:\Du-an\RouteFlow` |
| uv package cache | `D:\DevCache\uv\cache` |
| uv managed Python installations | `D:\DevCache\uv\python` |
| pip cache | `D:\DevCache\pip` |
| Google Cloud CLI config, logs and ADC | `D:\DevCache\gcloud` |
| Temporary files from the development wrapper | `D:\RouteFlow-storage\tmp` |
| Docker images, build cache, volumes and container logs | `E:\DockerDesktop\data\wsl` |
| Desktop host settings/logs/sockets (small Windows files) | Normal directory `C:\Users\ADMIN\AppData\Local\Docker` |
| Active Docker data disk | `E:\DockerDesktop\data\wsl\disk\docker_data.vhdx` |
| Registered Docker WSL runtime | `E:\DockerDesktop\data\wsl\main\ext4.vhdx` |
| WSL swap / crash dumps | `E:\DockerDesktop\wsl-swap.vhdx` / `E:\DockerDesktop\wsl-crashes` |
| Retained offline Docker migration copies | `E:\DockerDesktop\migration-backups-20261016` |

`scripts/dev.ps1` sets cache, managed-Python and temporary directories before invoking tools.
For Docker it additionally refuses to proceed unless Docker's **`CustomWslDistroDir`** points to E,
the saved data disk exists, the `docker-desktop` WSL registration uses its direct E path, and WSL
swap/crash settings point to E. Desktop startup may repair the runtime registration; workloads
are checked after startup. `DataFolder` alone does not select the WSL disk.
It does not download packages or start services merely to check storage.

```powershell
.\scripts\start-docker.ps1
.\scripts\dev.ps1 uv cache dir
.\scripts\dev.ps1 uv run ruff check .
.\scripts\dev.ps1 docker compose config --quiet
.\scripts\dev.ps1 docker compose up -d --build
```

Existing C Python cache/runtime paths are retained as junctions to D for compatibility with
installed tools and the existing virtual environment. **The earlier Docker root junction was
retired after the 4.95 update exposed a fresh default-C store.** Docker now uses its supported
`CustomWslDistroDir` setting for the direct E path. The former junction is preserved under
`Docker.routeflow-E-junction-preserved-20261016`; it is not the active Desktop root. Host sockets
and logs remain in a normal C directory; bulk storage and WSL swap remain on E.

`C:\Users\ADMIN\.wslconfig` configures `swapFile` and `crashDumpFolder` on E. These are global
WSL2 settings; this machine currently has only Docker's distribution. Docker/WSL was shut down
and restarted to apply them. Microsoft documents the path settings and escaped backslash syntax
in [WSL configuration](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).

The migration records previous running containers and image/volume names under
`D:\RouteFlow-storage\migration-20261016`. Offline VHD copies are verified by size and SHA256
before switching paths. Do not delete an original or temporary migration copy until Docker and
database counts have been checked against the new physical disk. No volume-prune or factory reset
is part of this migration.

This host also reproduced Docker Desktop's Secrets Engine startup failure on an orphaned
`engine.sock`, and after the update `run/sailor-ingest.sock`. See the primary
[Docker issue report](https://github.com/docker/for-win/issues/15064). Use `scripts/start-docker.ps1`
for a fresh start after quitting Desktop: it preserves the socket parent directory under a unique
backup name only when the backend is stopped and the contents are zero-byte socket files.
It also preserves the Desktop `run` directory before a fresh start to avoid stale Ingest sockets.
It refuses unexpected contents and never deletes them. If Desktop is already running, the script
leaves the socket directory alone. This is a local workaround; no Docker upgrade was installed.

Initially on 2026-10-16, Docker Engine 29.8.0 started successfully after the WSL runtime was re-registered
from a SHA256-verified VHD on E; Docker then placed the registration under its configured
`DataFolder` on E. Image/tag and volume inventories matched the pre-migration
snapshot. Source orders = 34, warehouse RAW events = 562, fact orders = 34, GPS daily rows = 9,
GPS points = 264, and estimated distance = 60.639007624322296 km. `haizflow-dashboard` was restarted.

Automatic approval review blocked deletion of old backup files. The large original C disks and
the abandoned D copy were therefore relocated to the retained backup folder on E instead of
being deleted. These offline copies consume about 76 GiB on E and are separate from the active
disk. They are not required for normal Docker operation; retain them until the owner chooses
to remove them. Small socket/configuration backup directories can remain on C. The inactive
pre-migration uv backup directories also remain on C (about 2 GiB); the active caches and Python
installations are on D. Final observed free space was approximately C = 46.09 GiB, D = 53.23 GiB,
E = 79.70 GiB after the WSL swap disk was created on E. These free-space figures are historical,
before the later recovery snapshot; see [update recovery](DOCKER_RECOVERY_VI.md) for current evidence.
