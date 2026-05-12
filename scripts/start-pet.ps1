<#
.SYNOPSIS
  Bootstrap + launch the desktop pet on Windows.

.DESCRIPTION
  First run creates .venv, installs requirements, generates sprites.
  Subsequent runs reuse the venv and skip work that's already done.

.PARAMETER Debug
  Enables PET_DEBUG=1 (prints geometry + draws a red outline window).

.PARAMETER Reset
  Wipes the .venv and reinstalls from scratch.

.PARAMETER Regen
  Regenerates sprite PNGs.

.EXAMPLE
  .\scripts\start-pet.ps1
  .\scripts\start-pet.ps1 -Debug
  .\scripts\start-pet.ps1 -Reset
#>

param(
    [switch]$Debug,
    [switch]$Reset,
    [switch]$Regen
)

$ErrorActionPreference = 'Stop'

function Write-Log    ($msg) { Write-Host "[start-pet] $msg" -ForegroundColor Cyan }
function Write-Warn   ($msg) { Write-Host "[start-pet] $msg" -ForegroundColor Yellow }
function Write-Die    ($msg) { Write-Host "[start-pet] $msg" -ForegroundColor Red; exit 1 }

# ---------- 1. locate project root ----------
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir '..')
Set-Location $ProjectRoot

$VenvDir   = Join-Path $ProjectRoot '.venv'
$VenvPy    = Join-Path $VenvDir 'Scripts\python.exe'
$ReqFile   = Join-Path $ProjectRoot 'requirements.txt'
$ReqStamp  = Join-Path $VenvDir '.requirements.sha256'
$SpriteDir = Join-Path $ProjectRoot 'pet\sprites'

# ---------- 2. find a real Python (avoid Microsoft Store stub) ----------
function Test-RealPython($exePath) {
    # Microsoft Store stubs live under WindowsApps and either open the Store
    # or exit with no output. A working Python prints its version string.
    if (-not (Test-Path $exePath)) { return $false }
    if ($exePath -like '*\WindowsApps\*') { return $false }
    try {
        $ver = & $exePath -c 'import sys; print(\"%d.%d\" % sys.version_info[:2])' 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $ver) { return $false }
        $parts = $ver.Trim().Split('.')
        return ([int]$parts[0] -gt 3) -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 9)
    } catch {
        return $false
    }
}

$PythonExe = $null

# Prefer the 'py' launcher when available (best Windows tool).
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    foreach ($spec in '-3.12','-3.11','-3.10','-3.9','-3') {
        try {
            $resolved = & $pyLauncher.Source $spec -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-RealPython $resolved.Trim())) {
                $PythonExe = $resolved.Trim()
                break
            }
        } catch { }
    }
}

# Fall back to whatever python/python3 is on PATH (skipping Store stubs).
if (-not $PythonExe) {
    foreach ($name in 'python','python3') {
        $cmds = Get-Command $name -All -ErrorAction SilentlyContinue
        foreach ($c in $cmds) {
            if (Test-RealPython $c.Source) {
                $PythonExe = $c.Source
                break
            }
        }
        if ($PythonExe) { break }
    }
}

if (-not $PythonExe) {
    Write-Warn 'No real Python 3.9+ was found on this machine.'
    Write-Warn 'Your PATH only has the Microsoft Store stub (which opens the Store).'
    Write-Warn ''
    Write-Warn 'Install Python first, pick one:'
    Write-Warn '  1) winget install -e --id Python.Python.3.12   (recommended)'
    Write-Warn '  2) https://www.python.org/downloads/  (check "Add to PATH" during install)'
    Write-Warn ''
    Write-Warn 'After installing, open a NEW PowerShell window and re-run this script.'
    Write-Die  'aborting.'
}
Write-Log "using $PythonExe ($(& $PythonExe --version 2>&1))"

# ---------- 3. (re)create venv ----------
if ($Reset -and (Test-Path $VenvDir)) {
    Write-Log "removing existing venv at $VenvDir"
    Remove-Item -Recurse -Force $VenvDir
}

if (-not (Test-Path $VenvPy)) {
    Write-Log "creating venv at $VenvDir"
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Write-Die "venv creation failed" }
}

# ---------- 4. install / refresh deps when requirements.txt changes ----------
$ReqHash = (Get-FileHash $ReqFile -Algorithm SHA256).Hash
$StampHash = if (Test-Path $ReqStamp) { Get-Content $ReqStamp -Raw } else { '' }

if ($ReqHash -ne $StampHash.Trim()) {
    Write-Log 'installing requirements (hash changed)'
    & $VenvPy -m pip install --upgrade pip | Out-Null
    & $VenvPy -m pip install -r $ReqFile
    if ($LASTEXITCODE -ne 0) { Write-Die "pip install failed" }
    Set-Content -Path $ReqStamp -Value $ReqHash -NoNewline
} else {
    Write-Log 'requirements up to date'
}

# ---------- 5. ensure sprites exist ----------
$NeedRegen = $false
if ($Regen) {
    $NeedRegen = $true
} elseif (-not (Test-Path (Join-Path $SpriteDir 'idle'))) {
    $NeedRegen = $true
} elseif (-not (Get-ChildItem (Join-Path $SpriteDir 'idle') -Filter '*.png' -ErrorAction SilentlyContinue)) {
    $NeedRegen = $true
}

if ($NeedRegen) {
    Write-Log 'generating sprite PNGs'
    & $VenvPy -m pet.generate_sprites
    if ($LASTEXITCODE -ne 0) { Write-Die "sprite generation failed" }
} else {
    Write-Log 'sprites present'
}

# ---------- 6. launch ----------
if ($Debug) {
    $env:PET_DEBUG = '1'
    Write-Log 'launching in DEBUG mode (red outline, verbose logs)'
} else {
    Write-Log 'launching'
}

if (-not $env:QT_ENABLE_HIGHDPI_SCALING) {
    $env:QT_ENABLE_HIGHDPI_SCALING = '1'
}

& $VenvPy (Join-Path $ProjectRoot 'pet_app.py')
exit $LASTEXITCODE
