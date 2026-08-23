$ErrorActionPreference = 'Stop'
$python = (Get-Command python -ErrorAction Stop).Source
$root = (Resolve-Path $PSScriptRoot).Path
Push-Location $root
try {
    & $python 'packaging\build_portable_release.py'
    if ($LASTEXITCODE -ne 0) {
        throw "Portable release build failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
