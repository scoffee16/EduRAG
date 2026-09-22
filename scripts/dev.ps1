#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

Set-Location $Root

if (-not (Test-Path -LiteralPath $Python)) {
    python -m venv $Venv
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -e ".[dev]"
& $Python -m uvicorn edurage.main:app --reload --host $BindHost --port $Port
