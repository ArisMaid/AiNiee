# RPG development contract

Date: 2026-10-16. Supervisor: Codex. Implementation worker: DeepSeek Harness.
Upstream baseline: 7bbb06be33f5968f0723a5200a150d895d4fa5fb.

The approved detailed plan is DEVELOPMENT_PLAN.md in the parent workspace. This
contract fixes interfaces for independently implemented components. Never modify
AGENTS.md, game inputs, credentials, Git internals, or supervisor acceptance tests.
No recursive deletion or automatic workspace cleanup. Test artifacts stay under
work/. Source games are outside this checkout and are read-only for Codex.

## Foundation interfaces (v1)

Package roots: ModuleFolders.Domain.GameProject and
ModuleFolders.Service.GameProject. Use Python 3.13 standard library. No Qt or
model SDK imports in core modules. Public model objects are dataclasses and expose
to_dict()/from_dict() for JSON-safe roundtrips.

Models.py:

- hash_text(text: str) -> lowercase SHA256 of UTF-8 logical string.
- Issue(code, severity, message, unit_id='', path='', details={}).
- Occurrence(occurrence_id, relative_path, locator: dict,
  expected_value_hash, adapter_id='rpgmaker-native', role='text', ordinal=0).
- TranslationUnit(unit_id, kind, source_text, scene_id='', context={},
  occurrences=(), token_policy_id='rpgmaker-v1', source_hash=''). Empty source_hash
  is computed; supplied nonmatching source_hash raises ValueError.
- TranslationProposal(unit_id, text, expected_source_hash,
  expected_revision=0, job_id='', request_item_id='', origin='manual', metadata={}).
- CommitResult(unit_id, status, revision=0, issues=()). status is one of accepted,
  rejected, conflict, locked, duplicate. Every object uses independent mutable
  defaults. Reject malformed JSON model input instead of accepting arbitrary keys.

PathGuard.py:

- PathViolation(ValueError) with code attribute.
- safe_join(root, relative_path, must_exist=False) -> resolved Path. Reject
  absolute paths (including Windows drive and UNC on any OS), traversal, ADS,
  empty segments, reserved Windows device names, symlinks/junctions and hardlinked
  files. Inspect lexical parents before resolution to catch reparse points.
- assert_disjoint(*roots) -> None; reject equal or ancestor/descendant roots with
  normalized case-insensitive Windows semantics, including nonexisting targets.
- atomic_write(path, data: bytes, overwrite=False) -> None. Refuse existing target
  by default, retain uniquely named failed staging files; no unlink or cleanup.

ProjectStore.py:

- ProjectStore.create(root, metadata: dict) -> store. root is an existing empty or
  new project directory; fail when project.sqlite3 already exists. Metadata needs
  project_id, source_root, engine; defaults schema_version=1, dataset_revision=0,
  content_revision=0. Open existing via ProjectStore(root).
- close(), context manager, metadata(), update_metadata(changes).
- put_files(records), files(): each record has relative_path, sha256, size,
  encoding='utf-8', captured_path='', adapter_id='rpgmaker-native'. Upsert only
  explicitly supplied records; no deletion of missing records.
- replace_units(units): first extraction insert; subsequent calls UPSERT matching
  IDs, mark disappeared units obsolete (no SQL DELETE), validate duplicate IDs,
  occurrences and source hashes. Bump dataset/content revisions once when changed.
  Preserve valid unchanged translations; changed source invalidates reuse.
- units(include_obsolete=False) -> list[TranslationUnit], unit(unit_id),
  translation(unit_id, target_language='zh-CN') -> dict or None.
- commit(proposal, issues=(), target_language='zh-CN') -> CommitResult: single
  transaction. Check unit exists/current, source hash, translation revision,
  manual lock and any error-severity issue. Accept valid result, increment
  translation revision and global content_revision, store edit and checkpoint.
  Invalid/conflicting/locked/late proposals stay in proposals without modifying
  accepted text. Unique nonempty (job_id, request_item_id, target_language)
  makes result delivery idempotent. Preserve empty manual text as untranslated.
- set_locked(unit_id, locked, target_language='zh-CN'). Lock can exist before
  first translation. Bump content_revision if state changes.
- put_issues(issues, job_id=''), issues(), proposals(), edits().
- create_job(operation, payload=None) -> job dict with job_id, run_state=QUEUED,
  stage, checkpoint; update_job(job_id, **changes), jobs(). Validate state changes
  against documented transitions. close/reopen must preserve all data.
- snapshot(destination): SQLite backup consistent across all tables; fail if
  destination exists; never copy live WAL file as a database backup.
- record_build(record), builds(): explicit build_id required, never overwrite an
  existing build with unrelated input digest.
- foreign keys enabled, parameterized SQL, WAL, busy timeout, serial writes under
  RLock, all revisions/accepted edits/proposal status in same transaction.
  No filesystem deletion, no SQL DELETE, no network or subprocess.

Do not broaden these interfaces without supervisor review. Invalid input should
raise ValueError or a domain ValueError subtype. Use pure, typed helpers.
