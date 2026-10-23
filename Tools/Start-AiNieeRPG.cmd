@echo off
setlocal DisableDelayedExpansion
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-AiNieeRPG.ps1"
set "rpgLaunchExit=%errorlevel%"
if not "%rpgLaunchExit%"=="0" pause
exit /b %rpgLaunchExit%
