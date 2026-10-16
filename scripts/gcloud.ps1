$ErrorActionPreference = 'Stop'
$gcloudArguments = @($args)
$configDirectory = 'D:\DevCache\gcloud'
New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
# Reuse the pinned emulator image already installed on E; never pull implicitly.
$image = 'gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators@sha256:dff831e11d4013af597446d43e1222a9196d9b2b0c8180606bb2e35bf1ea6e03'
$dockerArguments = @('run', '--rm', '--pull=never')
if ($gcloudArguments -contains 'login') {
    $dockerArguments += '-it'
    if ($gcloudArguments -notcontains '--no-launch-browser') {
        $gcloudArguments += '--no-launch-browser'
    }
}
$dockerArguments += @(
    '--mount', "type=bind,source=$configDirectory,target=/gcloud-config",
    '-e', 'CLOUDSDK_CONFIG=/gcloud-config', '--entrypoint', 'gcloud', $image
)
& (Join-Path $PSScriptRoot 'dev.ps1') docker @dockerArguments @gcloudArguments
exit $LASTEXITCODE
