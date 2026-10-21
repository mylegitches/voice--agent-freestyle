param(
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    python -m venv (Join-Path $root ".venv")
    & $python -m pip install --upgrade pip
    & $python -m pip install -r (Join-Path $root "requirements.txt")
}

if (-not (Test-Path -LiteralPath (Join-Path $root "web\dist\index.html"))) {
    Push-Location (Join-Path $root "web")
    try {
        npm install
        npm run build
    }
    finally {
        Pop-Location
    }
}

$arguments = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
if ($Reload) { $arguments += "--reload" }
& $python @arguments
