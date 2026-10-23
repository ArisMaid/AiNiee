param(
    [string]$Python = '',
    [string[]]$PytestArgs = @('tests/game_project', '-q', '--tb=short')
)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'rpg_paths.ps1')
$rpgPaths = Get-RpgPaths $repoPath
if (-not $Python) { $Python = $rpgPaths.python }
$env:PYTHONPYCACHEPREFIX = $rpgPaths.cache
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath $repoPath
foreach ($argument in $PytestArgs) {
    if ($argument -eq '--basetemp' -or $argument.StartsWith('--basetemp=') -or $argument.Contains('tmp_path_retention_')) {
        throw 'The no-delete test runner owns basetemp and retention options; choose test selectors or other pytest options instead.'
    }
}
$temporaryParent = Join-Path $rpgPaths.work 'acceptance\pytest-retained'
New-Item -ItemType Directory -Path $temporaryParent -Force | Out-Null
$temporaryPath = Join-Path $temporaryParent ([guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $temporaryPath) { throw 'Test destination must be new; existing data is retained.' }
# Do not create basetemp here. Pytest deletes an existing --basetemp before
# use; the fresh UUID and all-retention policy avoid that cleanup path.
$safeOptions = @('-p', 'no:cacheprovider', '-o', 'tmp_path_retention_policy=all', '--basetemp', $temporaryPath)
& $Python -m pytest @PytestArgs @safeOptions
$pytestExitCode = $LASTEXITCODE
Write-Output ('Retained test temporary files: ' + $temporaryPath)
exit $pytestExitCode
