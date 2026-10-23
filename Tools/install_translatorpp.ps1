param([string]$SevenZip = 'C:\Program Files\7-Zip\7z.exe')
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'rpg_paths.ps1')
$rpgPaths = Get-RpgPaths $repoPath
$installPath = Join-Path $rpgPaths.translatorpp '8.8.9'
$archivePath = Join-Path $installPath 'Translator++_8.8.9_x64_.51895b12.7z'
$appPath = Join-Path $installPath 'app'
$downloadUrl = 'https://github.com/dreamsavior/TranslatorPlusPlus/releases/download/8.8.9/Translator%2B%2B_8.8.9_x64_.51895b12.7z'
$expectedHash = '2389b58a1315870ca4bf3ee7b2eff06d65b2b635a5c56a9b3b0a59b1c1d9131c'
if (-not (Test-Path -LiteralPath $SevenZip -PathType Leaf)) { throw '7-Zip is required. Pass its full executable path with -SevenZip.' }
$ancestor = [System.IO.DirectoryInfo]$installPath
while ($null -ne $ancestor) {
    if ((Test-Path -LiteralPath $ancestor.FullName) -and
        ((Get-Item -LiteralPath $ancestor.FullName -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw 'Reparse points are not allowed in the installation path'
    }
    $ancestor = $ancestor.Parent
}
New-Item -ItemType Directory -Path $installPath -Force | Out-Null
if (-not (Test-Path -LiteralPath $archivePath)) {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath
}
$actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedHash) { throw 'Translator++ archive SHA-256 mismatch; file retained for inspection' }
if (Test-Path -LiteralPath $appPath) { throw 'Installation path exists; inspect or use the existing installation. Nothing overwritten.' }
& $SevenZip x '-pDreamsavior' '-bd' '-bso0' '-bsp0' ('-o' + $appPath) $archivePath
if ($LASTEXITCODE -ne 0) { throw 'Translator++ extraction failed; artifacts retained' }
$packagePath = Join-Path $appPath 'Translator++\package.json'
$packageInfo = Get-Content -LiteralPath $packagePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($packageInfo.version -ne '8.8.9') { throw 'Installed version differs from pinned version' }
$record = [ordered]@{version='8.8.9'; source=$downloadUrl; sha256=$actualHash; app_root=(Join-Path $appPath 'Translator++')}
$record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $installPath 'installation.json') -Encoding utf8
$record | ConvertTo-Json
