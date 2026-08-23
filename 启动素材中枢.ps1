$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) { $pythonCommand = Get-Command py -ErrorAction SilentlyContinue }
if (-not $pythonCommand) { throw '未找到 Python 3.11 或更高版本，请先安装 Python。' }
$python = $pythonCommand.Source

Set-Location -LiteralPath $root
& $python .\desktop.py
