function Get-RpgPaths([string]$RepoRoot) {
    $layout = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'rpg_paths.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $workspace = Split-Path -Parent $RepoRoot
    if ($env:RPG_WORKSPACE_ROOT) { $workspace = [IO.Path]::GetFullPath($env:RPG_WORKSPACE_ROOT) }
    $paths = @{}
    foreach ($entry in $layout.PSObject.Properties) { $paths[$entry.Name] = Join-Path $workspace $entry.Value }
    # Optional installer scripts also ship in portable packages. Keep their
    # existing package-local installation/profile convention.
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot 'RpgApp.py') -PathType Leaf)) {
        $paths.translatorpp = Join-Path $RepoRoot '.tools\translatorpp'
        $paths.ocr = Join-Path $RepoRoot '.tools\ocr'
        $paths.work = Join-Path $RepoRoot 'work'
    }
    return $paths
}
