$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([IO.Path]::GetPathRoot($projectRoot) -ne 'D:\') { throw 'Keep RouteFlow on D.' }
Write-Host 'RouteFlow Console: http://127.0.0.1:58090'
Write-Host 'Press Ctrl+C to stop the console. Docker services keep their current state.'
& (Join-Path $PSScriptRoot 'dev.ps1') uv run --frozen uvicorn routeflow.console:app --host 127.0.0.1 --port 58090 --no-access-log
exit $LASTEXITCODE
