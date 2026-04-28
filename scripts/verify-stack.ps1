[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> Backend health"
Invoke-RestMethod "http://localhost:18000/health" | ConvertTo-Json -Depth 5

Write-Host "==> Frontend reachability"
$frontend = Invoke-WebRequest "http://localhost:15173" -UseBasicParsing
Write-Host "Status:" $frontend.StatusCode

Write-Host "==> Admin pipeline"
$loginBody = @{ username = 'admin_demo'; password = 'Password123' } | ConvertTo-Json
$tokenResp = Invoke-RestMethod "http://localhost:18000/api/v1/auth/login" -Method Post -ContentType "application/json" -Body $loginBody
$headers = @{ Authorization = "Bearer $($tokenResp.access_token)" }
Invoke-RestMethod "http://localhost:18000/api/v1/admin/pipeline/jobs" -Headers $headers | ConvertTo-Json -Depth 6

Write-Host "==> Admin retrieval metrics"
Invoke-RestMethod "http://localhost:18000/api/v1/admin/system/retrieval-metrics" -Headers $headers | ConvertTo-Json -Depth 8

Write-Host "==> Admin backend status"
Invoke-RestMethod "http://localhost:18000/api/v1/admin/system/backends" -Headers $headers | ConvertTo-Json -Depth 8

Write-Host "==> Admin retrieval integrity"
Invoke-RestMethod "http://localhost:18000/api/v1/admin/system/retrieval-integrity?sample_size=8" -Headers $headers | ConvertTo-Json -Depth 8

Write-Host "==> Admin runtime metrics"
Invoke-RestMethod "http://localhost:18000/api/v1/admin/evaluation/runtime-metrics" -Headers $headers | ConvertTo-Json -Depth 8

Write-Host "==> Admin runtime metrics history"
Invoke-RestMethod "http://localhost:18000/api/v1/admin/evaluation/runtime-metrics/history?limit=5" -Headers $headers | ConvertTo-Json -Depth 8
