# UI and quality slice contract

Implement only the task's four allowed Python files. Read this document and the
existing GameProjectService, ProjectStore, TranslationCommitter and Models as
needed. No deletion, shell, network or execution. Codex owns integration/tests.

## FontInspector.py
`inspect_font(font_path, texts)` returns a plain JSON-safe dict with font_path,
sha256, character_count, missing_count, missing_characters (sorted unique list),
passed. Use fontTools.ttLib.TTFont, all Unicode cmap tables, always close font.
Ignore whitespace and Unicode Cc/Cf categories. A missing/unreadable font raises
ValueError. No game execution, no external font download, no font mutation.

`measure_layout(text, *, width_px, font_family, pixel_size=28)` uses PyQt5
QFontMetricsF only with an existing QApplication; return width_px, measured_width,
line_count, overflow and measurement='qt-estimate'. Respect explicit newlines.
Strip RPG Maker backslash controls conservatively using TokenPolicy.scan (inspect
its actual API), or accept a supplied already visible string if scanner differs.
Unknown commands must yield measurement='unverified-controls', not a pass.
Missing glyph evidence and estimated width are different; no runtime pass claim.

## MigrationService.py
`plan_migration(old_store, new_store)` returns {matches:[], review:[], stats:{}}.
Match by a canonical occurrence identity (relative_path + backend + JSON pointer
or JS object_path), source_hash and token_policy_id; units may have different IDs
between project versions. Require exactly one old candidate, nonstale translated
source, no locked target. Matches include old_unit_id,new_unit_id,text,
source_hash,expected_revision. Same text at a different locator or multiple
candidates -> review; never auto-match via fuzzy string. Include reason codes.
`apply_migration(old_store,new_store,plan)` submits through TranslationCommitter
with origin='migration', current hashes/revisions rechecked (no direct SQL).
Return list of CommitResult. Caller owns project writer lock. Revalidate plan
against a freshly generated plan to prevent arbitrary/stale plan text injection.

## GameProjectPage.py and __init__.py
Standalone `GameProjectPage(QWidget)` constructor `(parent=None, *, on_translate=None)`.
Use PyQt5 widgets, Chinese labels, no global Base/Config init. Codex wires mainnav.
Operations: source directory, new project directory, open existing game-project.json,
scan/create, extract, refresh, export JSON to selected *new file*, import JSON,
offline validate, test build / release build, choose output parent, summary,
issues and units. Display explicit incomplete translation count and runtime
validation state. Never auto-launch game or auto-send API requests.
All heavy operations run via QThread worker with plain results; each job opens
and closes its own service/SQLite connection. Disable conflicting controls while
busy, reject close while active (no QThread.terminate); errors visibly reported.
QAbstractTableModel + QTableView (no one QWidget per unit); columns unit_id,kind,
source,translation,status. Filter text and cap view only if UI clearly says so.
Double click a row to edit translation in a dialog and commit through service
import_translations with captured source_hash and expected_revision. Checkbox
manual lock optional via ProjectLock+store.set_locked. Never allow source edit.
Issues show severity/code/file/unit ID; choosing issue selects unit if present.
`set_project(path)` opens and refreshes; `project_root` property; `is_busy()`.
Provide `translateRequested` signal(str) and a button '送往 AiNiee 翻译' that emits
current project game-project.json path; main window owns cache/task integration.
Summary count and issue data must come from SQLite, not a second mutable cache.
Avoid extensive styling, mock features, TODO stubs or unsupported claims.
