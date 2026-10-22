param([switch]$Build)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([IO.Path]::GetPathRoot($projectRoot) -ne 'D:\') { throw 'Keep RouteFlow on D.' }
$wrapper = Join-Path $PSScriptRoot 'dev.ps1'
& $wrapper docker info --format '{{.DockerRootDir}}'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Path (Join-Path $projectRoot '.local/console'),'E:\DockerDesktop\console-metadata' -Force | Out-Null
& $wrapper uv run --frozen python -c 'import json; from pathlib import Path; from routeflow.console import storage_summary,timestamp; data=storage_summary(); data["observed_at"]=timestamp(); Path(".local/console/host.json").write_text(json.dumps(data),encoding="utf-8")'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $wrapper docker image inspect routeflow-console:local --format '{{.Id}}' 2>$null
if ($LASTEXITCODE -ne 0 -or $Build) {
    & $wrapper docker compose build --pull=false api
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $wrapper docker compose build --pull=false console
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $wrapper docker compose up -d --no-build --pull never console
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'RouteFlow Console: http://127.0.0.1:58090'
Write-Host 'Next time: Start the routeflow group in Docker Desktop, then open port 58090.'
