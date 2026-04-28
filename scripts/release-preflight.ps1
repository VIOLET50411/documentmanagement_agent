[CmdletBinding()]
param(
  [string]$BackendBaseUrl = "http://localhost:18000",
  [string]$FrontendUrl = "http://localhost:15173",
  [string]$Username = "admin_demo",
  [string]$Password = "Password123",
  [switch]$RunTests,
  [switch]$RunFrontendBuild,
  [switch]$RunLoadtest,
  [switch]$RunSmokeE2E
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$reportDir = Join-Path $root "reports\delivery"
New-Item -Path $reportDir -ItemType Directory -Force | Out-Null
$reportMd = Join-Path $reportDir "preflight_$timestamp.md"
$reportJson = Join-Path $reportDir "preflight_$timestamp.json"

$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
  param(
    [string]$Check,
    [bool]$Passed,
    [string]$Detail
  )
  $results.Add([PSCustomObject]@{
    check = $Check
    passed = $Passed
    detail = $Detail
    timestamp = (Get-Date).ToString("s")
  }) | Out-Null
  if ($Passed) {
    Write-Host "[PASS] $Check - $Detail" -ForegroundColor Green
  }
  else {
    Write-Host "[FAIL] $Check - $Detail" -ForegroundColor Red
  }
}

function Try-Check {
  param(
    [string]$Name,
    [scriptblock]$Script
  )
  try {
    & $Script
  }
  catch {
    Add-Result -Check $Name -Passed $false -Detail ($_.Exception.Message -replace "`r?`n", " ")
  }
}

function Invoke-WithRetry {
  param(
    [scriptblock]$Action,
    [int]$MaxAttempts = 4,
    [int]$DelaySeconds = 2
  )
  $last = $null
  for ($i = 1; $i -le $MaxAttempts; $i++) {
    try {
      return & $Action
    } catch {
      $last = $_
      if ($i -lt $MaxAttempts) {
        Start-Sleep -Seconds $DelaySeconds
      }
    }
  }
  if ($last) {
    throw $last
  }
  throw "retry action failed"
}

function Get-PortFromUrl {
  param([string]$Url)
  $uri = [System.Uri]$Url
  if ($uri.IsDefaultPort) {
    if ($uri.Scheme -eq "https") { return 443 }
    return 80
  }
  return $uri.Port
}

function Get-EndpointDiagnostic {
  param(
    [string]$BaseUrl,
    [string]$ComposeServiceHint
  )
  $messages = @()
  try {
    $port = Get-PortFromUrl -Url $BaseUrl
    $conn = Test-NetConnection -ComputerName "localhost" -Port $port -WarningAction SilentlyContinue
    if (-not $conn.TcpTestSucceeded) {
      $messages += "port_$port=closed"
    } else {
      $messages += "port_$port=open"
    }
  } catch {
    $messages += "port_check_error=$($_.Exception.Message)"
  }

  try {
    $docker = docker compose ps --format json 2>$null
    if ($LASTEXITCODE -eq 0 -and $docker) {
      $rows = $docker -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json }
      $service = $rows | Where-Object { $_.Service -eq $ComposeServiceHint } | Select-Object -First 1
      if ($service) {
        $messages += "docker_service_$ComposeServiceHint=$($service.State)"
      } else {
        $messages += "docker_service_$ComposeServiceHint=not_found"
      }
    } else {
      $messages += "docker_compose_status=unknown"
    }
  } catch {
    $messages += "docker_diag_error=$($_.Exception.Message)"
  }

  return ($messages -join "; ")
}

Try-Check "backend.health" {
  try {
    $health = Invoke-WithRetry -Action { Invoke-RestMethod "$BackendBaseUrl/health" -TimeoutSec 6 } -MaxAttempts 4 -DelaySeconds 2
    Add-Result "backend.health" ($health.status -eq "healthy") ("status=" + ($health.status | Out-String).Trim())
  } catch {
    $diag = Get-EndpointDiagnostic -BaseUrl $BackendBaseUrl -ComposeServiceHint "backend"
    throw "backend health failed: $($_.Exception.Message); diag: $diag"
  }
}

Try-Check "frontend.reachability" {
  try {
    $resp = Invoke-WithRetry -Action { Invoke-WebRequest $FrontendUrl -UseBasicParsing -TimeoutSec 6 } -MaxAttempts 3 -DelaySeconds 1
    Add-Result "frontend.reachability" ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) ("status_code=" + $resp.StatusCode)
  } catch {
    $diag = Get-EndpointDiagnostic -BaseUrl $FrontendUrl -ComposeServiceHint "frontend"
    throw "frontend reachability failed: $($_.Exception.Message); diag: $diag"
  }
}

$headers = $null
Try-Check "auth.login" {
  try {
    $body = @{ username = $Username; password = $Password } | ConvertTo-Json
    $tokenResp = Invoke-WithRetry -Action {
      Invoke-RestMethod "$BackendBaseUrl/api/v1/auth/login" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 8
    } -MaxAttempts 4 -DelaySeconds 2
    if (-not $tokenResp.access_token) { throw "missing access_token" }
    $script:headers = @{ Authorization = "Bearer $($tokenResp.access_token)" }
    Add-Result "auth.login" $true "token acquired"
  } catch {
    $diag = Get-EndpointDiagnostic -BaseUrl $BackendBaseUrl -ComposeServiceHint "backend"
    throw "auth login failed: $($_.Exception.Message); diag: $diag"
  }
}

if ($headers -ne $null) {
  Try-Check "admin.pipeline.jobs" {
    $resp = Invoke-RestMethod "$BackendBaseUrl/api/v1/admin/pipeline/jobs?limit=5" -Headers $headers -TimeoutSec 8
    Add-Result "admin.pipeline.jobs" $true ("jobs=" + ($resp.jobs.Count))
  }

  Try-Check "admin.system.backends" {
    $resp = Invoke-WithRetry -Action {
      Invoke-RestMethod "$BackendBaseUrl/api/v1/admin/system/backends" -Headers $headers -TimeoutSec 15
    } -MaxAttempts 3 -DelaySeconds 2
    Add-Result "admin.system.backends" $true ("redis=" + $resp.redis.available + ", milvus=" + $resp.milvus.available + ", es=" + $resp.elasticsearch.available)
  }

  Try-Check "admin.system.retrieval_metrics" {
    $resp = Invoke-RestMethod "$BackendBaseUrl/api/v1/admin/system/retrieval-metrics" -Headers $headers -TimeoutSec 8
    Add-Result "admin.system.retrieval_metrics" $true ("source=" + $resp.source)
  }

  Try-Check "admin.system.readiness" {
    $resp = Invoke-RestMethod "$BackendBaseUrl/api/v1/admin/system/readiness" -Headers $headers -TimeoutSec 8
    Add-Result "admin.system.readiness" $true ("score=" + $resp.score + ", ready=" + $resp.ready)
  }

  Try-Check "admin.system.retrieval_integrity" {
    $resp = Invoke-RestMethod "$BackendBaseUrl/api/v1/admin/system/retrieval-integrity?sample_size=8" -Headers $headers -TimeoutSec 12
    Add-Result "admin.system.retrieval_integrity" ([bool]$resp.healthy) ("score=" + $resp.score + ", healthy=" + $resp.healthy)
  }

  Try-Check "admin.evaluation.runtime_metrics" {
    $resp = Invoke-RestMethod "$BackendBaseUrl/api/v1/admin/evaluation/runtime-metrics" -Headers $headers -TimeoutSec 8
    Add-Result "admin.evaluation.runtime_metrics" $true ("citation_coverage=" + $resp.citation_coverage)
  }
}

if ($RunTests) {
  Try-Check "backend.pytest" {
    Push-Location "$root\backend"
    try {
      pytest -q | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "pytest exit=$LASTEXITCODE" }
      Add-Result "backend.pytest" $true "pytest passed"
    }
    finally {
      Pop-Location
    }
  }
}

if ($RunFrontendBuild) {
  Try-Check "frontend.build" {
    Push-Location "$root\frontend"
    try {
      npm.cmd run build | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "frontend build exit=$LASTEXITCODE" }
      Add-Result "frontend.build" $true "vite build passed"
    }
    finally {
      Pop-Location
    }
  }
}

if ($RunLoadtest) {
  Try-Check "baseline.loadtest" {
    py -3 scripts\loadtest_baseline.py --base-url $BackendBaseUrl --search-requests 20 --search-concurrency 10 --chat-requests 10 --chat-concurrency 5 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "loadtest exit=$LASTEXITCODE" }
    Add-Result "baseline.loadtest" $true "short profile passed"
  }
}

if ($RunSmokeE2E) {
  Try-Check "baseline.smoke_e2e" {
    $output = py -3 scripts\smoke_e2e.py --base-url $BackendBaseUrl --username $Username --password $Password
    if ($LASTEXITCODE -ne 0) { throw "smoke e2e exit=$LASTEXITCODE" }
    Add-Result "baseline.smoke_e2e" $true ("result=" + (($output | Out-String).Trim()))
  }
}

$passCount = @($results | Where-Object { $_.passed }).Count
$totalCount = $results.Count
$score = if ($totalCount -gt 0) { [math]::Round(($passCount / $totalCount) * 100, 2) } else { 0 }
$summary = [PSCustomObject]@{
  generated_at = (Get-Date).ToString("s")
  total_checks = $totalCount
  passed_checks = $passCount
  score = $score
  status = if ($score -ge 85) { "READY_CANDIDATE" } else { "NOT_READY" }
}

$jsonPayload = [PSCustomObject]@{
  summary = $summary
  results = $results
}
$jsonPayload | ConvertTo-Json -Depth 6 | Out-File -FilePath $reportJson -Encoding utf8

$md = @()
$md += "# DocMind Delivery Preflight Report"
$md += ""
$md += "- generated_at: $($summary.generated_at)"
$md += "- total_checks: $($summary.total_checks)"
$md += "- passed_checks: $($summary.passed_checks)"
$md += "- score: $($summary.score)"
$md += "- status: $($summary.status)"
$md += ""
$md += "## Check Results"
$md += ""
$md += "| Check | Passed | Detail |"
$md += "|---|---|---|"
foreach ($item in $results) {
  $md += "| $($item.check) | $($item.passed) | $($item.detail -replace '\|','/') |"
}
$md += ""
$md += "## Output Files"
$md += ""
$md += "- markdown: $reportMd"
$md += "- json: $reportJson"

$md -join "`r`n" | Out-File -FilePath $reportMd -Encoding utf8

Write-Host ""
Write-Host "==> Delivery preflight finished"
Write-Host "score: $score"
Write-Host "markdown: $reportMd"
Write-Host "json: $reportJson"
