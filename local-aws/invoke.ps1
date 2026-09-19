param(
    [ValidateSet('normal', 'sensor-failure', 'real-event')]
    [string]$Scenario = 'normal',
    [string]$EventFile
)
$ErrorActionPreference = 'Stop'
$body = @{ scenario = $Scenario } | ConvertTo-Json -Compress
if ($EventFile) { $body = Get-Content -LiteralPath $EventFile -Raw }
$result = Invoke-RestMethod -Uri 'http://127.0.0.1:3001/trust' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 120
if ($null -eq $result.trust_score -or $result.archive.provider -ne 'LocalStack S3') {
    throw 'Invocation did not return a trust score and LocalStack archive confirmation.'
}
$stored = Invoke-RestMethod -Uri 'http://127.0.0.1:4566/pulsetrust-local-results/latest.json'
if ($stored.execution.request_id -ne $result.execution.request_id) {
    throw 'Archived invocation does not match the returned result.'
}
$result | ConvertTo-Json -Depth 12
Write-Host 'Verified: SAM Lambda invocation and matching LocalStack S3 result.'
