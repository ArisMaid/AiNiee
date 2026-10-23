param([string]$SevenZip='C:\Program Files\7-Zip\7z.exe')
$ErrorActionPreference='Stop'
$repoPath=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'rpg_paths.ps1')
$rpgPaths=Get-RpgPaths $repoPath
$installPath=Join-Path $rpgPaths.ocr 'tesseract-5.4.0.20240606'
$archivePath=Join-Path $installPath 'tesseract-ocr-w64-setup-5.4.0.20240606.exe'
$appPath=Join-Path $installPath 'app'
$archiveUrl='https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe'
$archiveHash='c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9'
$dataCommit='87416418657359cb625c412a48b6e1d6d41c29bd'
$jpnHash='1f5de9236d2e85f5fdf4b3c500f2d4926f8d9449f28f5394472d9e8d83b91b4d'
if (-not (Test-Path -LiteralPath $SevenZip -PathType Leaf)) { throw '7-Zip is required' }
if (Test-Path -LiteralPath $appPath) { throw 'Installation exists; use it or select another checkout. No files overwritten.' }
$ancestor=[System.IO.DirectoryInfo]$installPath
while ($null -ne $ancestor) {
    if ((Test-Path -LiteralPath $ancestor.FullName) -and ((Get-Item -LiteralPath $ancestor.FullName -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { throw 'Reparse installation path rejected' }
    $ancestor=$ancestor.Parent
}
New-Item -ItemType Directory -Path $installPath -Force | Out-Null
if (-not (Test-Path -LiteralPath $archivePath)) { Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath }
if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $archiveHash) { throw 'Archive hash mismatch; retained for inspection' }
& $SevenZip x $archivePath ('-o'+$appPath) '-aos' '-bso0' '-bsp0'
if ($LASTEXITCODE -ne 0) { throw 'Archive extraction failed; files retained' }
$jpnPath=Join-Path $appPath 'tessdata\jpn.traineddata'
if (Test-Path -LiteralPath $jpnPath) { throw 'Unexpected Japanese data in archive; inspect before continuing' }
Invoke-WebRequest -Uri ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/'+$dataCommit+'/jpn.traineddata') -OutFile $jpnPath
if ((Get-FileHash -LiteralPath $jpnPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $jpnHash) { throw 'Japanese data hash mismatch; retained for inspection' }
& (Join-Path $appPath 'tesseract.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'OCR runtime failed' }
[ordered]@{version='5.4.0.20240606';source=$archiveUrl;sha256=$archiveHash;tessdata_commit=$dataCommit;jpn_sha256=$jpnHash;app_root=$appPath} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $installPath 'installation.json') -Encoding utf8
