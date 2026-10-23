param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'rpg_paths.ps1')
$rpgPaths = Get-RpgPaths $repoPath
Set-Location -LiteralPath $repoPath
$env:PYTHONPYCACHEPREFIX = $rpgPaths.cache
$env:PYTHONUTF8 = '1'
& $rpgPaths.python 'RpgApp.py' @Arguments
exit $LASTEXITCODE
