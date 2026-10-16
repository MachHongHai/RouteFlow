$ErrorActionPreference = 'Stop'

# This host leaves inaccessible AF_UNIX socket files after Desktop exits.
# Preserve the socket directory before a fresh start; never delete secret data.
if (-not (Get-Process -Name 'com.docker.backend' -ErrorAction SilentlyContinue)) {
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
exit $LASTEXITCODE
