$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$taskStatePath = Join-Path $taskRoot '.verification/laravel-connection.json'
if (-not (Test-Path -LiteralPath $taskStatePath)) {
    throw 'Local connection state is missing. Run the reviewed installer first.'
}
$taskState = [System.IO.File]::ReadAllText($taskStatePath) | ConvertFrom-Json
$taskApp = [System.IO.Path]::GetFullPath($taskState.source_path)
if (-not (Test-Path -LiteralPath (Join-Path $taskApp 'artisan'))) {
    throw 'The configured application is not available.'
}

function Test-TaskPort([int] $Port) {
    $taskSocket = [System.Net.Sockets.TcpClient]::new()
    try {
        $taskSocket.Connect('127.0.0.1', $Port)
        return $true
    } catch [System.Net.Sockets.SocketException] {
        return $false
    } finally {
        $taskSocket.Dispose()
    }
}

if (-not (Test-TaskPort 18000)) {
    $taskLauncher = Join-Path $taskRoot '.verification/start-hub.ps1'
    if (-not (Test-Path -LiteralPath $taskLauncher)) {
        throw 'The local Hub launcher is missing.'
    }
    & $taskLauncher *> (Join-Path $taskRoot '.verification/package-hub-launch.log')
    Write-Output 'Local Hub started.'
}
if (-not (Test-TaskPort 18881)) {
    $taskPhp = (Get-Command php -ErrorAction Stop).Source
    & $taskPhp -r 'exit(PHP_VERSION_ID < 80100 ? 1 : 0);'
    if ($LASTEXITCODE -ne 0) {
        throw 'This application needs PHP 8.1 or later; choose the matching CLI runtime.'
    }
    $taskStartOptions = @{
        FilePath = $taskPhp
        WindowStyle = 'Hidden'
        ArgumentList = @('-d', 'extension=sockets', 'artisan', 'serve', '--host=127.0.0.1', '--port=18881')
        WorkingDirectory = $taskApp
        PassThru = $true
        RedirectStandardOutput = (Join-Path $taskRoot '.verification/hireach-package.out.log')
        RedirectStandardError = (Join-Path $taskRoot '.verification/hireach-package.err.log')
    }
    $taskProcess = Start-Process @taskStartOptions
    [System.IO.File]::WriteAllText((Join-Path $taskRoot '.verification/hireach-package-pid.txt'), [string]$taskProcess.Id)
    Write-Output 'Local application started.'
}
Write-Output 'HiReach: http://127.0.0.1:18881'
Write-Output 'Existing listeners were preserved; no credentials or permissions were changed.'
