# Builds dist\CSS-ZE-Widget.exe. Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File build.ps1

$python = ".venv\Scripts\python.exe"

function Run {
    # PowerShell doesn't stop on a failing .exe by itself, so check each exit code.
    & $python @args
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}

Run -m pip install --quiet pyinstaller==6.22.3
Run make_ico.py build\icon.ico
Run -m PyInstaller main.py --onefile --noconsole --noconfirm --clean --log-level WARN --name CSS-ZE-Widget --icon build\icon.ico
