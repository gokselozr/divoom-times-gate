param()
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$packagePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $packagePython)) {
    throw 'Create .venv with Python 3.11+ first: py -3 -m venv .venv'
}
& $packagePython -m pip install --disable-pip-version-check -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Could not install the packaging dependencies.' }
& $packagePython -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; no package was built.' }
& $packagePython -m PyInstaller --noconfirm TimesGate.spec
if ($LASTEXITCODE -ne 0) { throw 'The EXE build failed.' }
& $packagePython package_release.py
if ($LASTEXITCODE -ne 0) { throw 'Could not create the release ZIP.' }
