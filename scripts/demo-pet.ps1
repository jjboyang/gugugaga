<#
.SYNOPSIS
  Cycle the running desktop pet through every phase so you can verify
  each animation looks right.

.DESCRIPTION
  Requires the pet to already be running (start-pet.ps1).
  Sends one phase notification, waits, then moves to the next.

.PARAMETER Seconds
  Seconds to dwell on each phase. Default: 3.
#>
param(
    [int]$Seconds = 3
)

$ErrorActionPreference = 'Stop'

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir '..')
$VenvPy      = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Notifier    = Join-Path $ScriptDir 'notify-pet.py'

if (-not (Test-Path $VenvPy)) {
    Write-Host "[demo-pet] venv not found. Run scripts\start-pet.ps1 first." -ForegroundColor Red
    exit 1
}

# Demo order: matches a realistic 'agent thinking' lifecycle, then back to idle.
$phases = @('idle','question','reading','thinking','writing','executing','done','idle')

Write-Host "[demo-pet] cycling through phases ($Seconds s each)..." -ForegroundColor Cyan
foreach ($p in $phases) {
    Write-Host ("[demo-pet] -> {0}" -f $p) -ForegroundColor Yellow
    & $VenvPy $Notifier $p
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[demo-pet] notify failed; is the pet running?" -ForegroundColor Red
        exit 1
    }
    Start-Sleep -Seconds $Seconds
}
Write-Host "[demo-pet] done." -ForegroundColor Green
