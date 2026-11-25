<#
.SYNOPSIS
  Bootstrap + launch the desktop pet on Windows.

.DESCRIPTION
  First run creates .venv, installs requirements, generates sprites.
  Subsequent runs reuse a compatible venv and skip work that's already done.

.PARAMETER Debug
  Enables PET_DEBUG=1 (prints geometry + draws a red outline window).

.PARAMETER Reset
  Wipes the .venv and reinstalls from scratch.

.PARAMETER Regen
  Regenerates sprite PNGs.

.EXAMPLE
  .\scripts\windows\start-pet.ps1
  .\scripts\windows\start-pet.ps1 -Debug
  .\scripts\windows\start-pet.ps1 -Reset
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
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir '..\..')
Set-Location $ProjectRoot

$VenvDir   = Join-Path $ProjectRoot '.venv'
$VenvPy    = Join-Path $VenvDir 'Scripts\python.exe'
$ReqFile   = Join-Path $ProjectRoot 'requirements.txt'
$ReqStamp  = Join-Path $VenvDir '.requirements.sha256'
$SpriteDir = Join-Path $ProjectRoot 'pet\sprites'

# ---------- 2. find a Python with compatible Windows wheels ----------
function Test-CompatiblePython($exePath) {
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) { return $false }
    # App execution aliases can open the Microsoft Store.
    if ($exePath -like '*\WindowsApps\*') { return $false }
    try {
        # PySide6 wheels require standard 64-bit CPython.
        $check = @(
            'import sys, sysconfig'
            'stable_version = (3, 11) <= sys.version_info[:2] < (3, 16) and sys.version_info.releaselevel == ''final'''
            'standard_64bit = sys.implementation.name == ''cpython'' and sys.maxsize > 2**32 and not sysconfig.get_config_var(''Py_GIL_DISABLED'')'
            'sys.exit(not (stable_version and standard_64bit))'
        ) -join '; '
        & $exePath -I -c $check >$null 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-CompatiblePython {
    $pyLauncher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($spec in '-3.12','-3.13','-3.14','-3.15','-3.11') {
            try {
                $resolved = & $pyLauncher.Source $spec -I -c 'import sys; print(sys.executable)' 2>$null
                if ($LASTEXITCODE -eq 0 -and $resolved) {
                    $candidate = $resolved.Trim()
                    if ($candidate -ne $VenvPy -and (Test-CompatiblePython $candidate)) {
                        return $candidate
                    }
                }
            } catch { }
        }
    }

    foreach ($name in 'python','python3') {
        $cmds = Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue
        foreach ($c in $cmds) {
            if ($c.Source -ne $VenvPy -and (Test-CompatiblePython $c.Source)) {
                return $c.Source
            }
        }
    }
}

# ---------- 3. (re)create venv ----------
if ($Reset -or -not (Test-CompatiblePython $VenvPy)) {
    $PythonExe = Find-CompatiblePython
    if (-not $PythonExe) {
        Write-Warn 'A standard 64-bit Python 3.11 through 3.15 is required for Windows.'
        Write-Warn 'Install Python 3.12 with: winget install -e --id Python.Python.3.12'
        Write-Warn 'Or use a 64-bit installer from https://www.python.org/downloads/windows/.'
        Write-Die 'Open a new PowerShell window after installing Python, then run this script again.'
    }

    if (Test-Path -LiteralPath $VenvDir) {
        if ($Reset) {
            Write-Log "removing existing venv at $VenvDir"
            Remove-Item -LiteralPath $VenvDir -Recurse -Force
        } else {
            $VenvBackup = Join-Path $ProjectRoot ".venv-backup-$([guid]::NewGuid().ToString('N'))"
            Write-Log "moving incompatible venv to $VenvBackup"
            Move-Item -LiteralPath $VenvDir -Destination $VenvBackup
        }
    }

    Write-Log "creating venv at $VenvDir with $PythonExe"
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Write-Die "venv creation failed" }
}
Write-Log "using $VenvPy ($(& $VenvPy --version 2>&1))"

# ---------- 4. install / refresh deps when requirements.txt changes ----------
$ReqHash = (Get-FileHash $ReqFile -Algorithm SHA256).Hash
$StampHash = if (Test-Path $ReqStamp) { Get-Content $ReqStamp -Raw } else { '' }

if ($ReqHash -ne $StampHash.Trim()) {
    Write-Log 'installing requirements (hash changed)'
    & $VenvPy -m pip install --upgrade pip | Out-Null
    & $VenvPy -m pip install --only-binary=:all: -r $ReqFile
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
