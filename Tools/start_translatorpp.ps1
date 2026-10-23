param([switch]$Headless)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'rpg_paths.ps1')
$rpgPaths = Get-RpgPaths $repoPath
$appRoot = Join-Path $rpgPaths.translatorpp '8.8.9\app\Translator++'
$executable = Join-Path $appRoot 'Translator++.exe'
$packageInfo = Get-Content -LiteralPath (Join-Path $appRoot 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($packageInfo.version -ne '8.8.9' -or -not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw 'Run Tools/install_translatorpp.ps1 to install the pinned official version first'
}
$profilePath = Join-Path $rpgPaths.work 'translatorpp\profile-8.8.9'
New-Item -ItemType Directory -Path $profilePath -Force | Out-Null
$existingProcess = Get-CimInstance Win32_Process -Filter "Name = 'Translator++.exe'" |
    Where-Object { $_.ExecutablePath -eq $executable }
if ($existingProcess) {
    Write-Output 'This installation is already running. Use tpp-probe to verify its API.'
    return
}
$launchArguments = @('--no-first-run','--disable-background-networking',('--user-data-dir="' + $profilePath + '"'))
if ($Headless) { $launchArguments += '--headless=new' }
$processInfo = Start-Process -FilePath $executable -WorkingDirectory $appRoot -ArgumentList $launchArguments -WindowStyle Hidden -PassThru
[ordered]@{pid=$processInfo.Id;app_root=$appRoot;endpoint='http://127.0.0.1:22883';headless=[bool]$Headless} | ConvertTo-Json
