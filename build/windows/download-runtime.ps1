param(
    [string]$OutputDir = "dist/windows-runtime"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$headers = @{
    "User-Agent" = "TALON Windows desktop build"
}
if ($env:GITHUB_TOKEN) {
    $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN"
}

function Get-LatestRelease {
    param([string]$Repository)

    Invoke-RestMethod `
        -Headers $headers `
        -Uri "https://api.github.com/repos/$Repository/releases/latest"
}

function Get-ReleaseAsset {
    param(
        [object]$Release,
        [string]$Pattern,
        [string]$Description
    )

    $asset = $Release.assets |
        Where-Object { $_.name -match $Pattern } |
        Select-Object -First 1
    if (-not $asset) {
        $names = ($Release.assets | ForEach-Object { $_.name }) -join ", "
        throw "Could not find $Description matching '$Pattern'. Available assets: $names"
    }
    $asset
}

function Save-ReleaseAsset {
    param(
        [object]$Asset,
        [string]$Destination
    )

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Invoke-WebRequest -Headers $headers -Uri $Asset.browser_download_url -OutFile $Destination
}

$runtimeRoot = Resolve-Path -LiteralPath "." | ForEach-Object {
    Join-Path $_.Path $OutputDir
}
$installerRoot = Join-Path $runtimeRoot "installers"
$i2pdRoot = Join-Path $runtimeRoot "i2pd"
$tempRoot = Join-Path $runtimeRoot ".tmp"

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $runtimeRoot
New-Item -ItemType Directory -Force -Path $installerRoot, $i2pdRoot, $tempRoot | Out-Null

$yggRelease = Get-LatestRelease "yggdrasil-network/yggdrasil-go"
$yggAsset = Get-ReleaseAsset `
    -Release $yggRelease `
    -Pattern "^yggdrasil-.*-amd64\.msi$" `
    -Description "Yggdrasil Windows amd64 MSI"
$yggMsi = Join-Path $installerRoot "yggdrasil.msi"
Save-ReleaseAsset -Asset $yggAsset -Destination $yggMsi

$i2pdRelease = Get-LatestRelease "PurpleI2P/i2pd"
$i2pdAsset = Get-ReleaseAsset `
    -Release $i2pdRelease `
    -Pattern "^i2pd_.*_win64_mingw\.zip$" `
    -Description "i2pd Win64 MinGW zip"
$i2pdZip = Join-Path $tempRoot "i2pd.zip"
Save-ReleaseAsset -Asset $i2pdAsset -Destination $i2pdZip
Expand-Archive -Path $i2pdZip -DestinationPath $i2pdRoot -Force

$i2pdExe = Get-ChildItem -Path $i2pdRoot -Filter "i2pd.exe" -Recurse |
    Select-Object -First 1
if (-not $i2pdExe) {
    throw "Downloaded i2pd archive did not contain i2pd.exe"
}
if ($i2pdExe.DirectoryName -ne $i2pdRoot) {
    Get-ChildItem -LiteralPath $i2pdExe.DirectoryName -Force |
        Copy-Item -Destination $i2pdRoot -Recurse -Force
}

Remove-Item -Recurse -Force $tempRoot

@(
    "yggdrasil_asset=$($yggAsset.name)"
    "yggdrasil_release=$($yggRelease.tag_name)"
    "i2pd_asset=$($i2pdAsset.name)"
    "i2pd_release=$($i2pdRelease.tag_name)"
) | Set-Content -Path (Join-Path $runtimeRoot "runtime-versions.txt") -Encoding UTF8

Write-Host "Bundled $($yggAsset.name)"
Write-Host "Bundled $($i2pdAsset.name)"
