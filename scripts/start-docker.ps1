$ErrorActionPreference = 'Stop'

# This host leaves inaccessible AF_UNIX socket files after Desktop exits.
# Preserve the socket directory before a fresh start; never delete secret data.
if (-not (Get-Process -Name 'com.docker.backend' -ErrorAction SilentlyContinue)) {
    $settings = Get-Content -LiteralPath "$env:APPDATA\Docker\settings-store.json" -Raw | ConvertFrom-Json
    if ($settings.CustomWslDistroDir -ne 'E:\DockerDesktop\data\wsl') {
        throw 'CustomWslDistroDir must point to the existing E disk before starting Desktop. See DOCKER_RECOVERY_VI.md.'
    }
    $runPath = Join-Path $env:LOCALAPPDATA 'Docker\run'
    if (Test-Path -LiteralPath $runPath) {
        if ((Get-Item -LiteralPath $runPath).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Unexpected Docker run directory link; inspect before starting.'
        }
        Rename-Item -LiteralPath $runPath -NewName ('run.routeflow-socket-backup-' + [guid]::NewGuid().ToString('N'))
    }
    $socketPath = Join-Path $env:LOCALAPPDATA 'docker-secrets-engine'
    if (Test-Path -LiteralPath $socketPath) {
        $socketDirectory = Get-Item -LiteralPath $socketPath
        $socketFiles = @(Get-ChildItem -LiteralPath $socketPath -Force)
        if (($socketDirectory.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            @($socketFiles | Where-Object {
                $_.PSIsContainer -or $_.Name -notin @('engine.sock', 'engine.sock.stale') -or $_.Length -ne 0
            }).Count -gt 0) {
            throw 'Unexpected Secrets Engine directory contents; inspect before restarting Docker.'
        }
        $backupName = 'docker-secrets-engine.routeflow-socket-backup-' + [guid]::NewGuid().ToString('N')
        Rename-Item -LiteralPath $socketDirectory.FullName -NewName $backupName
    }
}

& (Join-Path $PSScriptRoot 'dev.ps1') docker desktop start
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $PSScriptRoot 'dev.ps1') docker info --format '{{.ServerVersion}}'
exit $LASTEXITCODE
