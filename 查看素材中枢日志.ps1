$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$settingsPath = Join-Path $env:LOCALAPPDATA 'MuseVault\settings.json'
$logPath = Join-Path $root 'data\logs'

if (Test-Path -LiteralPath $settingsPath) {
    $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($settings.log_root) {
        $logPath = $settings.log_root
    }
}

New-Item -ItemType Directory -Path $logPath -Force | Out-Null
Start-Process explorer.exe -ArgumentList $logPath
