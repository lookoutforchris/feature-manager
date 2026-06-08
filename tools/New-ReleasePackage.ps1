[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$OutputDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) "dist")
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $repoRoot "FeatureManager.manifest"

if (-not $Version) {
    $manifestText = Get-Content -LiteralPath $manifestPath -Raw
    $match = [regex]::Match($manifestText, '"version"\s*:\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "Could not read version from manifest: $manifestPath"
    }
    $Version = $match.Groups[1].Value
}

$packageRoot = Join-Path $OutputDirectory "FeatureManager-$Version"
$addInRoot = Join-Path $packageRoot "FeatureManager"
$archivePath = Join-Path $OutputDirectory "FeatureManager-$Version.zip"

if (Test-Path -LiteralPath $packageRoot) {
    Remove-Item -LiteralPath $packageRoot -Recurse -Force
}
if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}

New-Item -ItemType Directory -Path $addInRoot -Force | Out-Null

$items = @(
    "FeatureManager.py",
    "FeatureManager.manifest",
    "palette.html",
    "LICENSE",
    "README.md"
)

foreach ($item in $items) {
    $source = Join-Path $repoRoot $item
    $destination = Join-Path $addInRoot $item

    if (-not (Test-Path -LiteralPath $source)) {
        throw "Required release item does not exist: $source"
    }

    Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
}

$resourceRoot = Join-Path $addInRoot "resources\featuremanager"
New-Item -ItemType Directory -Path $resourceRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot "resources\featuremanager\16x16.png") -Destination $resourceRoot -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "resources\featuremanager\32x32.png") -Destination $resourceRoot -Force

$libraryRoot = Join-Path $addInRoot "featuremanagerlib"
New-Item -ItemType Directory -Path (Join-Path $libraryRoot "win") -Force | Out-Null
Copy-Item -Path (Join-Path $repoRoot "featuremanagerlib\*.py") -Destination $libraryRoot -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "featuremanagerlib\LICENSE") -Destination $libraryRoot -Force
Copy-Item -Path (Join-Path $repoRoot "featuremanagerlib\win\*.py") -Destination (Join-Path $libraryRoot "win") -Force

Compress-Archive -LiteralPath $addInRoot -DestinationPath $archivePath -Force
Write-Host "Created release package: $archivePath"
