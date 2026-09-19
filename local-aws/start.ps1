$ErrorActionPreference = 'Stop'
foreach ($tool in @('docker', 'sam')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool is missing. See local-aws/README.md for setup."
    }
}
Push-Location $PSScriptRoot
try {
    docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop with Linux containers.' }
    docker compose -f compose.yaml up -d
    if ($LASTEXITCODE -ne 0) { throw 'LocalStack could not start.' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            Invoke-RestMethod -Uri 'http://127.0.0.1:4566/pulsetrust-local-results' -Method Put | Out-Null
            $ready = $true
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'LocalStack S3 did not become ready. Check docker compose logs.' }
    # SAM gets local dummy values, never an existing AWS credential profile.
    $names = @('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_PROFILE', 'AWS_DEFAULT_PROFILE', 'AWS_DEFAULT_REGION', 'AWS_EC2_METADATA_DISABLED', 'SAM_CLI_TELEMETRY')
    $saved = @{}
    foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
    try {
        $env:AWS_ACCESS_KEY_ID = 'test'
        $env:AWS_SECRET_ACCESS_KEY = 'test'
        Remove-Item Env:AWS_SESSION_TOKEN, Env:AWS_PROFILE, Env:AWS_DEFAULT_PROFILE -ErrorAction SilentlyContinue
        $env:AWS_DEFAULT_REGION = 'us-east-1'
        $env:AWS_EC2_METADATA_DISABLED = 'true'
        $env:SAM_CLI_TELEMETRY = '0'
        sam build --template-file template.yaml
        if ($LASTEXITCODE -ne 0) { throw 'SAM image build failed.' }
        Write-Host 'Ready to start SAM. In a second terminal run: .\local-aws\invoke.ps1'
        sam local start-api --template .aws-sam/build/template.yaml --host 127.0.0.1 --port 3001 --docker-network pulsetrust-local-aws --region us-east-1
        if ($LASTEXITCODE -ne 0) { throw 'SAM local API stopped with an error.' }
    } finally {
        foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    }
} finally { Pop-Location }
