[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallPath = (Join-Path $env:APPDATA "Autodesk\Autodesk Fusion 360\API\AddIns\FeatureManager")
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

$items = @(
    "FeatureManager.py",
    "FeatureManager.manifest",
    "palette.html",
    "resources",
    "featuremanagerlib"
)

if (-not (Test-Path -LiteralPath $InstallPath -PathType Container)) {
    New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
}

foreach ($item in $items) {
    $source = Join-Path $repoRoot $item
    $destination = Join-Path $InstallPath $item

    if (-not (Test-Path -LiteralPath $source)) {
        throw "Required source item does not exist: $source"
    }

    if ($PSCmdlet.ShouldProcess($destination, "copy from $source")) {
        Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
    }
}

if ($WhatIfPreference) {
    Write-Host "Previewed Feature Manager add-in sync to: $InstallPath"
} else {
    Write-Host "Synced Feature Manager add-in files to: $InstallPath"
}
