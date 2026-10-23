param(
    [Parameter(Mandatory=$true)][string]$PackageZip,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSha256,
    [string]$DestinationRoot = ''
)
$ErrorActionPreference = 'Stop'
if (-not $DestinationRoot) {
    . (Join-Path $PSScriptRoot 'rpg_paths.ps1')
    $rpgPaths = Get-RpgPaths (Split-Path -Parent $PSScriptRoot)
    $DestinationRoot = $rpgPaths.sandbox
}
$rpgArchive = (Get-Item -LiteralPath $PackageZip).FullName
if ((Get-FileHash -LiteralPath $rpgArchive -Algorithm SHA256).Hash -ine $ExpectedSha256) { throw 'Package SHA-256 mismatch' }
$rpgKitRoot = Join-Path ([IO.Path]::GetFullPath($DestinationRoot)) ([guid]::NewGuid().ToString('N'))
$rpgInput = Join-Path $rpgKitRoot 'input'
$rpgResults = Join-Path $rpgKitRoot 'results'
New-Item -ItemType Directory -Path $rpgInput | Out-Null
New-Item -ItemType Directory -Path $rpgResults | Out-Null
Copy-Item -LiteralPath $rpgArchive -Destination (Join-Path $rpgInput 'AiNieeRPG.zip')
$rpgGuest = @'
param([Parameter(Mandatory=$true)][string]$ExpectedSha256)
$ErrorActionPreference = 'Stop'
$guestEvidence = Join-Path 'C:\RpgResults' ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $guestEvidence | Out-Null
$guestLocal = Join-Path 'C:\' ('RpgLocal-' + [guid]::NewGuid().ToString('N'))
$guestLocalEvidence = Join-Path $guestLocal 'evidence'
New-Item -ItemType Directory -Path $guestLocalEvidence | Out-Null
$guestReport = [ordered]@{
    checks_passed = $false
    clean_machine_accepted = $false
    scope = 'Guest checks only; host must independently confirm actual Sandbox execution and review evidence'
    computer_name = $env:COMPUTERNAME
    os_version = [Environment]::OSVersion.VersionString
    started_utc = [DateTime]::UtcNow.ToString('o')
    external_commands_before_path_restriction = @()
    package_sha256 = $null
    steps = @()
}
try {
    $guestReport.external_commands_before_path_restriction = @(Get-Command -Name python.exe,python3.exe,node.exe -CommandType Application -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
    $guestReport.package_sha256 = (Get-FileHash -LiteralPath 'C:\RpgInput\AiNieeRPG.zip' -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($guestReport.package_sha256 -ine $ExpectedSha256) { throw 'Guest package SHA-256 mismatch' }
    $guestSoftware = Join-Path $guestLocal 'software'
    Expand-Archive -LiteralPath 'C:\RpgInput\AiNieeRPG.zip' -DestinationPath $guestSoftware
    $guestExe = Join-Path $guestSoftware 'AiNieeRPG\AiNieeRPG.exe'
    $guestReport.executable = $guestExe
    $guestReport.executable_sha256 = (Get-FileHash -LiteralPath $guestExe -Algorithm SHA256).Hash.ToLowerInvariant()
    $env:PATH = Join-Path $env:SystemRoot 'System32'
    $env:AINIEE_OFFLINE = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    # SQLite workspaces belong on the guest's local disk. The mapped folder
    # publishes completed evidence only; Sandbox mapped storage can return I/O errors.
    $env:AINIEE_USER_DATA_DIR = Join-Path $guestLocalEvidence 'user'
    $env:AINIEE_CACHE_DIR = Join-Path $guestLocalEvidence 'cache'
    $env:AINIEE_PROJECT_CACHE_DIR = Join-Path $guestLocalEvidence 'project-cache'
    $env:AINIEE_LOG_DIR = Join-Path $guestLocalEvidence 'logs'
    Set-Location -LiteralPath $guestLocal
    $guestSelf = Join-Path $guestLocalEvidence 'selfcheck'
    $guestStep = Start-Process -FilePath $guestExe -ArgumentList @('--self-check',$guestSelf) -WorkingDirectory $guestLocal -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $guestLocalEvidence 'selfcheck.stdout') -RedirectStandardError (Join-Path $guestLocalEvidence 'selfcheck.stderr')
    $guestReport.steps += @{name='selfcheck';exit_code=$guestStep.ExitCode}
    if ($null -eq $guestStep.ExitCode -or $guestStep.ExitCode -ne 0) { throw 'Self-check exit code missing or nonzero; inspect retained stdout/stderr' }
    $guestSelfResult = Get-Content -LiteralPath (Join-Path $guestLocalEvidence 'selfcheck.stdout') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $guestSelfResult.passed) { throw 'Self-check report did not pass' }
    $guestProject = Join-Path $guestSelfResult.retained_artifacts 'project'
    $guestGui = Join-Path $guestLocalEvidence 'gui'
    $guestStep = Start-Process -FilePath $guestExe -ArgumentList @('--gui-check',$guestGui,'--project',$guestProject) -WorkingDirectory $guestLocal -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $guestLocalEvidence 'gui.stdout') -RedirectStandardError (Join-Path $guestLocalEvidence 'gui.stderr')
    $guestReport.steps += @{name='gui';exit_code=$guestStep.ExitCode}
    if ($null -eq $guestStep.ExitCode -or $guestStep.ExitCode -ne 0) { throw 'GUI check exit code missing or nonzero; inspect retained stdout/stderr' }
    $guestGuiResult = Get-Content -LiteralPath (Join-Path $guestGui 'gui-result.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $guestGuiResult.passed) { throw 'GUI report did not pass' }
    $guestReport.gui_result = $guestGuiResult
    $guestReport.selfcheck_result = $guestSelfResult
    $guestReport.no_external_python_or_node_on_original_path = ($guestReport.external_commands_before_path_restriction.Count -eq 0)
    $guestReport.checks_passed = $guestReport.no_external_python_or_node_on_original_path
    # Match the separately verified native-GUI launch. Keep its live user/cache
    # outside the completed-check evidence copied below, and capture console I/O.
    $guestNormal = Join-Path $guestLocal 'normal'
    New-Item -ItemType Directory -Path $guestNormal | Out-Null
    $env:AINIEE_PORTABLE = '1'
    $env:QT_QPA_PLATFORM = 'windows'
    $env:QT_DEBUG_PLUGINS = '1'
    $env:PYTHONUNBUFFERED = '1'
    $env:AINIEE_USER_DATA_DIR = Join-Path $guestNormal 'user'
    $env:AINIEE_CACHE_DIR = Join-Path $guestNormal 'cache'
    $env:AINIEE_PROJECT_CACHE_DIR = Join-Path $guestNormal 'project-cache'
    $env:AINIEE_LOG_DIR = Join-Path $guestNormal 'logs'
    $guestApp = Start-Process -FilePath $guestExe -ArgumentList @('--offline','--project',$guestProject) -WorkingDirectory $guestNormal -WindowStyle Normal -PassThru -RedirectStandardOutput (Join-Path $guestNormal 'startup.stdout') -RedirectStandardError (Join-Path $guestNormal 'startup.stderr')
    $guestReport.interactive_gui_process_id = $guestApp.Id
    $guestReport.interactive_gui_local_logs = $guestNormal
    $guestReport.interactive_gui_visual_acceptance = 'not_confirmed'
} catch {
    $guestReport.error = $_.Exception.Message
} finally {
    $guestReport.finished_utc = [DateTime]::UtcNow.ToString('o')
    Copy-Item -LiteralPath $guestLocalEvidence -Destination $guestEvidence -Recurse
    $guestReport | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath (Join-Path $guestEvidence 'result.json') -Encoding UTF8
}
if (-not $guestReport.checks_passed) { exit 1 }
exit 0
'@
[IO.File]::WriteAllText((Join-Path $rpgInput 'guest.ps1'), $rpgGuest, [Text.UTF8Encoding]::new($true))
$rpgEscapedInput = [Security.SecurityElement]::Escape($rpgInput)
$rpgEscapedResults = [Security.SecurityElement]::Escape($rpgResults)
$rpgConfig = @"
<Configuration>
  <Networking>Disable</Networking>
  <MappedFolders>
    <MappedFolder><HostFolder>$rpgEscapedInput</HostFolder><SandboxFolder>C:\RpgInput</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$rpgEscapedResults</HostFolder><SandboxFolder>C:\RpgResults</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand><Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\RpgInput\guest.ps1 -ExpectedSha256 $ExpectedSha256</Command></LogonCommand>
</Configuration>
"@
$rpgWsb = Join-Path $rpgKitRoot 'Acceptance.wsb'
[IO.File]::WriteAllText($rpgWsb, $rpgConfig, [Text.UTF8Encoding]::new($true))
@{prepared=$true;launched=$false;enabled_host_features=$false;wsb=$rpgWsb;results=$rpgResults;package_sha256=$ExpectedSha256.ToLowerInvariant()} | ConvertTo-Json
