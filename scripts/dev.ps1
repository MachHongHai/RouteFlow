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
$env:TEMP = 'D:\RouteFlow-storage\tmp'
$env:TMP = $env:TEMP
foreach ($directory in @($env:UV_CACHE_DIR, $env:PIP_CACHE_DIR, $env:TEMP)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

if ($Tool -eq 'docker') {
    $dockerData = Get-Item -LiteralPath "$env:LOCALAPPDATA\Docker" -Force
    if ($dockerData.LinkType -ne 'Junction' -or
        [IO.Path]::GetFullPath([string]$dockerData.Target) -ne 'E:\DockerDesktop\data') {
        throw 'Docker data is not verified on E. Do not build or start new workloads until storage migration is complete.'
    }
    $dockerSettings = Get-Content -LiteralPath "$env:APPDATA\Docker\settings-store.json" -Raw | ConvertFrom-Json
    $wslRegistration = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' |
        ForEach-Object { Get-ItemProperty -LiteralPath $_.PSPath } |
        Where-Object { $_.DistributionName -eq 'docker-desktop' })
    if ($dockerSettings.DataFolder -ne 'E:\DockerDesktop\data\wsl' -or
        $wslRegistration.Count -ne 1 -or
        $wslRegistration[0].BasePath -ne '\\?\E:\DockerDesktop\data\wsl\main') {
        throw 'Docker or WSL storage settings no longer point to the verified E locations.'
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
