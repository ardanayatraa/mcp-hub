# Start the Hub API and the admin UI together. Ctrl+C stops both.
#   .\dev.ps1                  settings from dev.env (created with fresh keys on the first run)
#   .\dev.ps1 -EnvFile x.env   settings from another file
param([string]$EnvFile = (Join-Path $PSScriptRoot 'dev.env'))

$ErrorActionPreference = 'Stop'
$backend = Join-Path $PSScriptRoot 'backend'
$frontend = Join-Path $PSScriptRoot 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) { Push-Location $backend; uv sync --frozen --group dev; Pop-Location }
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) { Push-Location $frontend; pnpm install --frozen-lockfile; Pop-Location }

if (-not (Test-Path $EnvFile)) {
    $database = (Join-Path (Split-Path $EnvFile) 'dev.db').Replace('\', '/')
    $key = & $python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    $signing = & $python -c "import secrets; print(secrets.token_urlsafe(48))"
    $password = & $python -c "import secrets; print('Hub-' + secrets.token_hex(4) + '-Aa1')"
    [IO.File]::WriteAllLines($EnvFile, @(
        'ENVIRONMENT=dev'
        "DATABASE_URL=sqlite+pysqlite:///$database"
        "SECRET_ENCRYPTION_KEY=$key"
        "SESSION_SIGNING_KEY=$signing"
        "ADMIN_INITIAL_PASSWORD=$password"
        'COOKIE_SECURE=false'
        'ALLOW_INSECURE_HTTP=true'
        'EGRESS_ALLOW_LOOPBACK=true'
        'EGRESS_ALLOWED_PORTS=80,443,8081'
        'ALLOWED_HOSTS=localhost,127.0.0.1,127.0.0.1:8000,127.0.0.1:5173'
        'ALLOWED_ORIGINS=http://127.0.0.1:5173'
        'MCP_PUBLIC_URL=http://127.0.0.1:8000/mcp'
        'MCP_ISSUER_URL=http://127.0.0.1:8000'
        'HUB_PORT=8000'
        'UI_PORT=5173'
    ))
    Write-Host "Created $EnvFile. Sign in as admin@localhost with password $password"
}

foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*([A-Za-z_]\w*)\s*=\s*(.*)$') { Set-Item "env:$($Matches[1])" $Matches[2].Trim() }
}
$hubPort = if ($env:HUB_PORT) { $env:HUB_PORT } else { '8000' }
$uiPort = if ($env:UI_PORT) { $env:UI_PORT } else { '5173' }

# An older Hub or UI still holding the port is stopped; anything else is left alone.
function Clear-Port([string]$port, [string]$pattern) {
    foreach ($id in Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $id"
        if ($process.CommandLine -notmatch $pattern) { throw "Port $port is taken by $($process.Name) (pid $id). Pick another port in $EnvFile." }
        Stop-Process -Id $id -Force
    }
    while (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 200 }
}
Clear-Port $hubPort 'uvicorn.+app\.main:app'
Clear-Port $uiPort 'vite'

Push-Location $backend
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    & $python -m app.bootstrap
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    $hub = Start-Process $python -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', $hubPort, '--no-access-log' -WorkingDirectory $backend -NoNewWindow -PassThru

    Write-Host "Hub API: http://127.0.0.1:$hubPort   Admin UI: http://127.0.0.1:$uiPort"
    $env:HUB_API_TARGET = "http://127.0.0.1:$hubPort"
    Set-Location $frontend
    pnpm exec vite --host 127.0.0.1 --port $uiPort --strictPort
}
finally {
    if ($hub -and -not $hub.HasExited) { taskkill /T /F /PID $hub.Id | Out-Null }
    Pop-Location
}
