[CmdletBinding()]
param(
  [switch]$InfraOnly,
  [switch]$NoInstall
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

Write-Host "==> Working directory: $root"
Set-Location $root

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Created .env from .env.example"
}

Write-Host "==> Starting infrastructure containers"
docker compose up -d postgres redis etcd minio milvus elasticsearch neo4j

if ($InfraOnly) {
  Write-Host "Infrastructure started. Skipping local app startup."
  exit 0
}

if (-not $NoInstall) {
  Write-Host "==> Installing backend dependencies"
  Set-Location "$root\\backend"
  py -3 -m pip install -r requirements.txt

  Write-Host "==> Installing frontend dependencies"
  Set-Location "$root\\frontend"
  npm.cmd install
}

Write-Host "==> Start backend in a new terminal"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\\backend'; py -3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

Write-Host "==> Start celery worker in a new terminal"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\\backend'; py -3 -m celery -A celery_app worker --loglevel=info --autoscale=8,2"

Write-Host "==> Start frontend in a new terminal"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\\frontend'; npm.cmd run dev -- --host 0.0.0.0 --port 5173"

Write-Host "Backend:  http://localhost:8000"
Write-Host "Frontend: http://localhost:5173"
Write-Host "Demo user: admin_demo / Password123"
