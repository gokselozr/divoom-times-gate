param([switch]$Demo)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$dashboardPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

function Test-Python($command, $code) {
    # Windows PowerShell 5.1 turns native stderr into errors; a failed probe is just "no".
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
        $rest = @($command | Select-Object -Skip 1)
        & $command[0] @rest -c $code 2>&1 | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Test-Venv {
    # A .venv copied from another computer points at a Python that may not exist here.
    if (-not (Test-Path -LiteralPath $dashboardPython)) { return $false }
    return Test-Python @($dashboardPython) "import PIL, tkinter"
}

if (-not (Test-Venv)) {
    $python = $null
    foreach ($candidate in @(@('py','-3'), @('python'), @('python3'))) {
        if (Get-Command $candidate[0] -ErrorAction SilentlyContinue) {
            if (Test-Python $candidate "import sys; sys.exit(sys.version_info < (3, 11))") { $python = $candidate; break }
        }
    }
    if (-not $python) { throw 'Python 3.11 or newer not found. Install it from python.org.' }
    if (Test-Path -LiteralPath '.venv') { Remove-Item -LiteralPath '.venv' -Recurse -Force }
    $pyArgs = @($python | Select-Object -Skip 1)
    & $python[0] @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
    & $dashboardPython -m pip install --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the dependencies.' }
}

# Idempotent: connects Claude Code's status line to this copy of the project.
& $dashboardPython setup_claude.py
if ($LASTEXITCODE -ne 0) { Write-Warning 'Could not install the Claude telemetry bridge; Claude limits may not show.' }

$dashboardArgs = @('app.py')
if ($Demo) { $dashboardArgs += '--demo' }
& $dashboardPython @dashboardArgs
