$ErrorActionPreference = 'Stop'
$python = (Get-Command python -ErrorAction Stop).Source
$root = (Resolve-Path $PSScriptRoot).Path
Push-Location $root
try {
    # The script has already changed into the packaging directory above.
    # Calling it through packaging\ would resolve to packaging\packaging\... .
    & $python 'build_installer.py'
    if ($LASTEXITCODE -ne 0) {
        throw "Installer build failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
