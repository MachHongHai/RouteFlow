$ErrorActionPreference = 'Stop'
# Keep raw arguments so Docker's -d is not consumed as PowerShell's -Debug.
$Tool = 'uv'
$Arguments = @()
if ($args.Count -gt 0) {
    $Tool = [string]$args[0]
    if ($args.Count -gt 1) {
        $Arguments = @($args[1..($args.Count - 1)])
    }
}
if ($Tool -notin @('uv', 'docker')) {
    throw 'Supported tools: uv, docker.'
}
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ([IO.Path]::GetPathRoot($projectRoot) -ne 'D:\') {
    throw 'RouteFlow must remain on D for this workstation.'
}

$env:UV_CACHE_DIR = 'D:\DevCache\uv\cache'
$env:UV_PYTHON_INSTALL_DIR = 'D:\DevCache\uv\python'
$env:PIP_CACHE_DIR = 'D:\DevCache\pip'
$env:CLOUDSDK_CONFIG = 'D:\DevCache\gcloud'
$env:TEMP = 'D:\RouteFlow-storage\tmp'
$env:TMP = $env:TEMP
$env:COMPOSE_FILE = (Join-Path $projectRoot 'docker-compose.yml') + ';' + (Join-Path $projectRoot 'docker-compose.windows.yml')
foreach ($directory in @($env:UV_CACHE_DIR, $env:PIP_CACHE_DIR, $env:CLOUDSDK_CONFIG, $env:TEMP)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

if ($Tool -eq 'docker') {
    $dockerSettings = Get-Content -LiteralPath "$env:APPDATA\Docker\settings-store.json" -Raw | ConvertFrom-Json
    $wslRegistration = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' |
        ForEach-Object { Get-ItemProperty -LiteralPath $_.PSPath } |
        Where-Object { $_.DistributionName -eq 'docker-desktop' })
    if ($dockerSettings.CustomWslDistroDir -ne 'E:\DockerDesktop\data\wsl' -or
        -not (Test-Path -LiteralPath 'E:\DockerDesktop\data\wsl\disk\docker_data.vhdx')) {
        throw 'Docker WSL data is not pinned to E. Do not create fresh volumes or rebuild; inspect the saved disk and recovery guide.'
    }
    $isDesktopStart = $Arguments.Count -ge 2 -and $Arguments[0] -eq 'desktop' -and $Arguments[1] -eq 'start'
    if (-not $isDesktopStart -and ($wslRegistration.Count -ne 1 -or
        $wslRegistration[0].BasePath -ne '\\?\E:\DockerDesktop\data\wsl\main')) {
        throw 'Docker WSL runtime no longer points to E. Start Desktop with the helper, then inspect registration before running workloads.'
    }
    $wslSettings = Get-Content -LiteralPath "$env:USERPROFILE\.wslconfig"
    if ($wslSettings -notcontains 'swapFile=E:\\DockerDesktop\\wsl-swap.vhdx' -or
        $wslSettings -notcontains 'crashDumpFolder=E:\\DockerDesktop\\wsl-crashes') {
        throw 'WSL swap or crash storage no longer points to E.'
    }
}

Push-Location $projectRoot
try {
    & $Tool @Arguments
    $toolExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $toolExit
