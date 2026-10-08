# AETHEL Colony - Bootstrap external CAIOS / Project Andrew
# Preserves the CAIOS repository as a separate GPL-3.0 dependency.
param(
  [string]$Target = "$PSScriptRoot\..\external\chaos-persona"
)

$ErrorActionPreference = "Stop"
$repo = "https://github.com/ELXaber/chaos-persona.git"
$commit = "cabe1d0b77c5080f86f49cc2a7c230785e0ceb8e"

if (-not (Test-Path $Target)) {
  git clone $repo $Target
} elseif (-not (Test-Path (Join-Path $Target ".git"))) {
  throw "Target exists but is not a Git checkout: $Target"
}

git -C $Target fetch --tags --prune origin
git -C $Target checkout --detach $commit

$ca = Join-Path $Target "Project_Andrew\CAIOS.txt"
$license = Join-Path $Target "LICENSE.txt"
if (-not (Test-Path $ca)) { throw "CAIOS.txt missing from pinned checkout" }
if (-not (Test-Path $license)) { throw "LICENSE.txt missing from pinned checkout" }

Write-Host "CAIOS checkout pinned to $commit"
Write-Host "Set CAIOS_SOURCE_PATH to $Target\Project_Andrew"
Write-Host "Required attribution: Built on CAIOS v1.0 by inventor Jonathan M. Schack – Patent Pending US 19/433,771 & 19/390,493 – www.cai-os.com"
