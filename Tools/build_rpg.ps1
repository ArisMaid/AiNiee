param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'rpg_paths.ps1')
$rpgPaths = Get-RpgPaths $repoPath
if (-not $Python) { $Python = $rpgPaths.python }
$env:PYTHONPYCACHEPREFIX = $rpgPaths.cache
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath $repoPath
$buildKey = [guid]::NewGuid().ToString('N')
$distPath = Join-Path $rpgPaths.dist $buildKey
$workPath = Join-Path $rpgPaths.work ('package\' + $buildKey)
if ((Test-Path -LiteralPath $distPath) -or (Test-Path -LiteralPath $workPath)) { throw 'Build destination must be new' }
& $Python -m PyInstaller --distpath $distPath --workpath $workPath 'Tools\pack_rpg.spec'
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed; diagnostic files retained' }
$appDir = Join-Path $distPath 'AiNieeRPG'
[System.IO.File]::WriteAllText((Join-Path $appDir 'portable.txt'), 'AiNiee RPG portable')
foreach ($launcherName in @('Start-AiNieeRPG.cmd','Start-AiNieeRPG.ps1')) {
    Copy-Item -LiteralPath (Join-Path $repoPath ('Tools\'+$launcherName)) -Destination (Join-Path $appDir $launcherName)
}
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\USER_GUIDE.md') -Destination (Join-Path $appDir '使用说明.md')
foreach ($documentName in @('EXTERNAL_TOOLS.md','RELEASE_7.2.4.1.md','EXTERNAL_TOOLS_EVIDENCE_7.2.4.1.md')) {
    Copy-Item -LiteralPath (Join-Path $repoPath ('docs\rpg\'+$documentName)) -Destination (Join-Path $appDir $documentName)
}
foreach ($documentName in @('IMPLEMENTATION_STATUS.md','BACKEND_EVIDENCE.md','TRANSLATORPP_EVIDENCE.md','JOB_RECOVERY.md','IMAGE_EVIDENCE.md','DEVELOPMENT_PLAN.md','FORMAT_V2_EVIDENCE.md','NUIIT_EVIDENCE.md','FONT_ALIAS_EVIDENCE.md','PROFILE3_EVIDENCE.md','MIGRATION_V2_EVIDENCE.md','CONTROL_R_EVIDENCE.md','F02_UI_BATTLE_EVIDENCE.md','C04_OWNERSHIP_EVIDENCE.md','VALIDATION_RECOVERY_EVIDENCE.md','EXTRACTION_RECOVERY_EVIDENCE.md','MIGRATION_REVIEW_EVIDENCE.md','MIGRATION_RECOVERY_EVIDENCE.md','NATIVE_PROCESS_CONTRACT.md','PROCESS_OWNERSHIP_EVIDENCE.md','PROFILE5_EVIDENCE.md','BACKEND_COMPARISON_EVIDENCE.md','COMMAND_AUDIT_EVIDENCE.md','RPGMTL_COMMON_EVIDENCE.md','TALKLIST_EXCLUSION_EVIDENCE.md','COMPARISON_REVIEW_EVIDENCE.md')) {
    Copy-Item -LiteralPath (Join-Path $repoPath ('docs\rpg\'+$documentName)) -Destination (Join-Path $appDir $documentName)
}
$optionalToolsPath=Join-Path $appDir 'Tools'
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\RUNTIME_CAPTURE_EVIDENCE.md') -Destination (Join-Path $appDir 'RUNTIME_CAPTURE_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\FULL_OUTPUT_RUNTIME_EVIDENCE.md') -Destination (Join-Path $appDir 'FULL_OUTPUT_RUNTIME_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\CUSTOM_JSON_SCOPE_EVIDENCE.md') -Destination (Join-Path $appDir 'CUSTOM_JSON_SCOPE_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\DIRECT_DISPLAY_EVIDENCE.md') -Destination (Join-Path $appDir 'DIRECT_DISPLAY_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\DISPLAY_LABELS_EVIDENCE.md') -Destination (Join-Path $appDir 'DISPLAY_LABELS_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\E03_FOLLOWUPS_EVIDENCE.md') -Destination (Join-Path $appDir 'E03_FOLLOWUPS_EVIDENCE.md')
foreach ($documentName in @('FAILED_RETRIES_EVIDENCE.md','SCAN_EVIDENCE.md','WORKER_PROTOCOL_DECISION.md','REQUIREMENT_COMPLETION_AUDIT.md','SANDBOX_ACCEPTANCE.md','KIND_PROMPTS_EVIDENCE.md','DERIVED_STATUS_EVIDENCE.md')) {
    Copy-Item -LiteralPath (Join-Path $repoPath ('docs\rpg\'+$documentName)) -Destination (Join-Path $appDir $documentName)
}
foreach ($documentName in @('CURRENT_BUILD_RECOVERY_EVIDENCE.md','PORTABLE_SCOPE.md','FONT_LAYOUT_EVIDENCE.md','FONT_COVERAGE_EVIDENCE.md','NOTE_TAG_EVIDENCE.md','NOTE_GROUPS_EVIDENCE.md','NOTE_CONSUMERS_EVIDENCE.md','NOTE_FOLLOWUPS_EVIDENCE.md')) {
    Copy-Item -LiteralPath (Join-Path $repoPath ('docs\rpg\'+$documentName)) -Destination (Join-Path $appDir $documentName)
}
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\RPGMTL_JS_EVIDENCE.md') -Destination (Join-Path $appDir 'RPGMTL_JS_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\GUI_WORKFLOW_EVIDENCE.md') -Destination (Join-Path $appDir 'GUI_WORKFLOW_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\STORE_PREPARATION_EVIDENCE.md') -Destination (Join-Path $appDir 'STORE_PREPARATION_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\COMPACT_UI_EVIDENCE.md') -Destination (Join-Path $appDir 'COMPACT_UI_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\BACKEND_CURRENT_GAME_EVIDENCE.md') -Destination (Join-Path $appDir 'BACKEND_CURRENT_GAME_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\SEXTRACTOR_MAIN_EVIDENCE.md') -Destination (Join-Path $appDir 'SEXTRACTOR_MAIN_EVIDENCE.md')
Copy-Item -LiteralPath (Join-Path $repoPath 'docs\rpg\STEV_PROJECT_EVIDENCE.md') -Destination (Join-Path $appDir 'STEV_PROJECT_EVIDENCE.md')
foreach ($documentName in @('MANUAL_EDIT_ATOMIC_EVIDENCE.md','SCENE_BATCH_EVIDENCE.md','E02_REMAINING_FIELDS_EVIDENCE.md','WRITE_ENTRYPOINT_AUDIT.md','CONTEXT_PREPARATION_EVIDENCE.md','MAIN_TASK_SCOPE_EVIDENCE.md','TABLE_TASK_SCOPE_EVIDENCE.md','PROOFREAD_SCOPE_EVIDENCE.md','ANALYSIS_WORKFLOW_EVIDENCE.md','PROFILE6_EVIDENCE.md','PROFILE7_EVIDENCE.md','PROFILE8_EVIDENCE.md')) {
    Copy-Item -LiteralPath (Join-Path $repoPath ('docs\rpg\'+$documentName)) -Destination (Join-Path $appDir $documentName)
}
New-Item -ItemType Directory -Path $optionalToolsPath | Out-Null
foreach ($toolName in @('install_translatorpp.ps1','start_translatorpp.ps1','install_tesseract.ps1','rpg_paths.ps1','rpg_paths.json')) {
    Copy-Item -LiteralPath (Join-Path $repoPath ('Tools\'+$toolName)) -Destination (Join-Path $optionalToolsPath $toolName)
}
& (Join-Path $appDir 'AiNieeRPG.exe') --self-check (Join-Path $workPath 'selfcheck')
if ($LASTEXITCODE -ne 0) { throw 'Packaged self-check failed; all artifacts retained' }
Write-Output $appDir
