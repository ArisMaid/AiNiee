param(
    [string]$Project,
    [string]$DataRoot,
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
$rpgAppRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$rpgUnsupportedPathChars = [char[]]'[]`'
if ($rpgAppRoot.IndexOfAny($rpgUnsupportedPathChars) -ge 0) {
    throw 'Extract the app to a local folder without square brackets or backticks (PowerShell 5.1 path limitation).'
}
$rpgExecutable = Join-Path $rpgAppRoot 'AiNieeRPG.exe'
if (-not (Test-Path -LiteralPath $rpgExecutable -PathType Leaf)) {
    throw 'Place both Start-AiNieeRPG files beside the extracted AiNieeRPG.exe.'
}
$rpgArguments = @()
if ($Project) {
    $Project = [System.IO.Path]::GetFullPath($Project)
    if (-not (Test-Path -LiteralPath $Project -PathType Container)) { throw 'Project directory not found.' }
    # Start-Process on Windows PowerShell 5.1 joins ArgumentList into one command line.
    # Quote the path, doubling trailing backslashes before the closing quote.
    $rpgArguments += '--project'
    $rpgArguments += '"' + [regex]::Replace($Project, '(\\+)$', '$1$1') + '"'
}
if ($Offline) { $rpgArguments += '--offline' }
$rpgChanges = @{
    AINIEE_PORTABLE = '1'
    AINIEE_OFFLINE = $(if ($Offline) { '1' } else { '0' })
    QT_QPA_PLATFORM = 'windows'
    PYTHONIOENCODING = 'utf-8'
    PYTHONUNBUFFERED = '1'
}
if ($DataRoot) {
    $DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
    $rpgChanges['AINIEE_USER_DATA_DIR'] = Join-Path $DataRoot 'user'
    $rpgChanges['AINIEE_CACHE_DIR'] = Join-Path $DataRoot 'cache'
    $rpgChanges['AINIEE_PROJECT_CACHE_DIR'] = Join-Path $DataRoot 'project-cache'
    $rpgChanges['AINIEE_LOG_DIR'] = Join-Path $DataRoot 'logs'
}
$rpgLogRoot = $rpgChanges['AINIEE_LOG_DIR']
if (-not $rpgLogRoot) { $rpgLogRoot = $env:AINIEE_LOG_DIR }
if (-not $rpgLogRoot) { $rpgLogRoot = Join-Path $rpgAppRoot 'Logs' }
if ($rpgLogRoot.IndexOfAny($rpgUnsupportedPathChars) -ge 0) {
    throw 'Use a log/data folder without square brackets or backticks (PowerShell 5.1 path limitation).'
}
$rpgLaunchLogs = Join-Path $rpgLogRoot ('launch\' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($rpgLaunchLogs) | Out-Null
$rpgPrevious = @{}
try {
    foreach ($rpgName in $rpgChanges.Keys) {
        $rpgPrevious[$rpgName] = [Environment]::GetEnvironmentVariable($rpgName, 'Process')
        [Environment]::SetEnvironmentVariable($rpgName, $rpgChanges[$rpgName], 'Process')
    }
    $rpgStart = @{
        FilePath = $rpgExecutable
        WorkingDirectory = $rpgAppRoot
        WindowStyle = 'Normal'
        PassThru = $true
        RedirectStandardOutput = Join-Path $rpgLaunchLogs 'startup.stdout'
        RedirectStandardError = Join-Path $rpgLaunchLogs 'startup.stderr'
    }
    if ($rpgArguments.Count -gt 0) { $rpgStart['ArgumentList'] = $rpgArguments }
    $rpgStarted = Start-Process @rpgStart
    [ordered]@{
        started_utc = [DateTime]::UtcNow.ToString('o')
        process_id = $rpgStarted.Id
        executable = $rpgExecutable
        project = $Project
        isolated_data_root = $DataRoot
        offline = [bool]$Offline
        gui_confirmed = $false
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $rpgLaunchLogs 'startup-info.json') -Encoding UTF8
    Write-Host ('Process started. Logs: ' + $rpgLaunchLogs)
    Write-Host 'Confirm the main window visually. This launcher does not certify GUI readiness.'
} finally {
    foreach ($rpgName in $rpgPrevious.Keys) {
        [Environment]::SetEnvironmentVariable($rpgName, $rpgPrevious[$rpgName], 'Process')
    }
}
