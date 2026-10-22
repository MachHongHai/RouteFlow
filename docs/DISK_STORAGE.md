# Optional Windows storage policy

The base Compose file uses Docker volumes and has no D/E drive requirement. The optional
PowerShell helpers enforce a specific Windows layout: source and host caches on D, Docker/WSL
bulk storage on E. Use them only after configuring that layout.

| Data | Helper configuration |
|---|---|
| Repository, virtual environment, local artifacts | Checkout on D |
| uv cache / managed Python | `D:\DevCache\uv\cache` / `D:\DevCache\uv\python` |
| pip / npm caches | `D:\DevCache\pip` / `D:\DevCache\npm` |
| Google Cloud CLI config and ADC | `D:\DevCache\gcloud` |
| Host temporary files | `D:\RouteFlow-storage\tmp` |
| Docker WSL root | `E:\DockerDesktop\data\wsl` |
| Docker bulk data disk | `E:\DockerDesktop\data\wsl\disk\docker_data.vhdx` |
| Docker WSL runtime | `E:\DockerDesktop\data\wsl\main\ext4.vhdx` |
| WSL swap / crash dumps | `E:\DockerDesktop\wsl-swap.vhdx` / `E:\DockerDesktop\wsl-crashes` |

Small Docker Desktop host settings, logs, and sockets can still use the Windows profile on C.
The helpers control project caches and Docker bulk placement; they do not relocate every
Windows application file.

## Storage checks

`scripts/dev.ps1` sets cache, managed-Python, cloud configuration, and temporary paths before
invoking uv or Docker. For Docker it also checks:

- `CustomWslDistroDir` in `$env:APPDATA\Docker\settings-store.json` points to the E root above.
- The existing bulk data disk is present.
- The `docker-desktop` WSL registration uses the direct E runtime path.
- `$env:USERPROFILE\.wslconfig` places swap and crash dumps on E.

The wrapper checks existing storage; it does not migrate a Docker installation.
If checks fail, inspect the active store before building or creating volumes. See the
[recovery runbook](DOCKER_RECOVERY_VI.md). `DataFolder` alone is not the WSL disk setting
checked by these helpers.

The wrapper selects `docker-compose.yml` plus `docker-compose.windows.yml`. The override mounts
read-only Windows settings and host metadata for the console's workstation policy. Missing
metadata blocks controls. The portable base file instead uses the selected Docker Engine's
volume storage without asserting a Windows drive location.

```powershell
.\scripts\start-docker.ps1
.\scripts\dev.ps1 uv cache dir
.\scripts\dev.ps1 uv run ruff check .
.\scripts\dev.ps1 docker compose config --quiet
```

For frontend tooling, set cache and temporary paths before npm:

```powershell
$env:npm_config_cache = 'D:\DevCache\npm'
$env:TEMP = 'D:\RouteFlow-storage\tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:npm_config_cache, $env:TEMP -Force | Out-Null
npm ci --ignore-scripts
npm run check
```

## Desktop startup helper

`scripts/start-docker.ps1` checks the E storage setting before starting Desktop and validates
the WSL registration afterward. With the backend stopped, it preserves stale socket directories
under unique backup names; unexpected contents cause it to stop. It does not prune volumes
or delete the data disk.

Back up existing VHDs offline before changing storage paths. Verify copies and database contents
before retiring an old store. WSL swap/crash settings are global to WSL2; see
[Microsoft's WSL configuration reference](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).
