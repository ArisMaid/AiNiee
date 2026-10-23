# Patch packaging contract

Implement ONLY `ModuleFolders/Service/GameProject/PatchService.py`. Use read/write/edit
only. No grep/glob/todo/shell/agents/network/deletion/dependency changes. Codex owns
integration, review and tests. Exact optional reads: this contract,
ModuleFolders/Service/GameProject/BuildService.py and PathGuard.py.
Prefer direct functions and small helpers; avoid generic frameworks.

Stdlib only plus local `safe_join`, `assert_disjoint`, `atomic_write`, `BuildService`,
`file_hash`, `write_json`. All paths support Chinese/spaces. Never execute game code.

`export_patch(store, build_path, target_file)`:
- hold ProjectLock(store.root), import exact local ProjectLock.py if needed.
- target absolute parent disjoint from original source_root. safe_join target.parent,
  target.name rejects reparse/hardlink/ADS/reserved paths. Refuse existing target.
- read build manifest UTF-8, require project_id==store.metadata project_id, then
  BuildService.verify(build_path) passed. Source and build are disjoint.
- Generate version1 `rpg-patch.json` with format='ainiee-rpg-patch', project_id,
  source_build_id, input_digest, mode, source_files and files. No absolute paths,
  credentials, private logs or game title. source_files = every build manifest row
  whose original_sha256 is not None, entries {path,sha256,size} using the store's
  source record size and hash, require matching store file record hash. Rows with
  original_sha256 None are new outputs (font/capture etc), never source requirements.
- `files` only rows where output_sha256!=original_sha256, each {path,
  original_sha256,output_sha256,size}; output bytes read and hashed AGAIN before zip.
- ZIP entries exactly `rpg-patch.json` and `files/<relativepath>` for changed/new
  files. Archive to a BytesIO (max 256 MiB changed uncompressed total) then
  atomic_write target, no overwrites. Refuse >256 MiB with clear error. This only
  avoids huge in-memory patches; no downloads or recursive cleanup.
- Return {patch_path,sha256,changed_files:<count>,source_file_count,mode}.

`apply_patch(source_root, patch_file, output_root, progress=None)` (name clashes
only with tools namespace, fine inside module):
- No DB needed. Absolute roots, safe_join boundaries, source and output_root
  disjoint. patch_file must not be inside source (read-only path okay but prevent
  confusing accidental output root overlap). Never mutate source or existing output.
- Read ZIP manifest max16 MiB; reject duplicate member names, encrypted entries,
  symlink Unix mode, invalid format/schema/metadata/hashes/sizes/path types.
  Validate every source_files/files path with safe_join(root,path), reject Windows
  casefold duplicate paths (also new output vs source differing only by case).
  SHA values strict 64 hex; size nonbool int >=0. source total <=16 GiB; changes
  <=256 MiB. Reject ZIP members not exactly manifest + changed listed paths;
  refuse unsafe '../', absolute, ADS or reparse paths via safe_join, never extractall.
- For each changed entry original_sha256 must match its source_files hash if that
  path exists there; if new, original_sha256 must be None and source path absent.
  Size and output hash of each ZIP payload verified. Stored ZIP file_size must
  equal manifest size. Ignore nothing silently.
- Check disk budget source total + changes total +64MiB.
- Validate all source hashes BEFORE writing output. Build a NEW UUID staging path
  inside output_root, copy only listed source files with open('xb'), streaming and
  fsync. Check copy hash again. Overlay changed bytes with atomic_write overwrite
  True only for files already copied into this new staging; new files use False.
  No directory deletion, shell, or copytree with overwrite.
- If progress, callback(completed,total,relativepath) once per source file.
- Rehash all sources at the end, detect concurrent source changes. Save standard
  rpg-build-manifest.json + rpg-build-complete.json compatible with BuildService.verify:
  schema_version1, build_id=new UUID, project_id,input_digest, mode, runtime_validation
  'not_run', files[{path,original_sha256,output_sha256}], output_path=final path.
- Rename complete staging to NEW game-zh-CN-patch-UUID final directory (refuse
  existing). Keep every failed staging and do NOT mark it complete or reuse it.
- Return generated build manifest including output_path. No best-effort rollback.

Specific errors may be ValueError with stable clear code. Codex will test a small
synthetic game, exact source preservation, new output fonts, wrong version/source,
duplicate/traversal/member/hash/size tampering and no-overwrite. Do not add tests.
