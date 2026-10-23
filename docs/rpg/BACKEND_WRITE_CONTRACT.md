# Memory-only third-party write contract

Implement ONLY `ModuleFolders/Infrastructure/GameAdapters/BackendWriters.py`.
Use read/write/edit only, no grep/glob/todo/shell/network/agents/deletion.
Codex owns parent subprocess protocol, approval boundaries, tests and acceptance.
Exact optional reads:
- ModuleFolders/Infrastructure/GameAdapters/BackendWorker.py
- StevExtraction/jtpp.py
- work/vendor/RPGMTL/plugins/json.py
- work/vendor/RPGMTL/plugins/__init__.py
- work/vendor/SExtractor/src/extract_RPGMV.py

Implement `write_document(backend,backend_root,relative_path,source:bytes,changes:list)`
called INSIDE a fresh dedicated worker process. Never call a whole app, importer,
CLI, ReadGame/InjectGame, mainExtract, project Save, patch/fix script, spreadsheet
export, or any directory/file writing routine. Only the memory APIs below.
All third-party stdout/stderr suppressed inside a bounded capture; return no raw logs.

Input changes exactly {pointer,source_text,text}, string keys/values, unique
non-root JSON pointers. Source UTF-8 with optional BOM. Limit 12 MiB source, 16 MiB
JSON output. Reject unknown backend, unsafe relative paths and malformed pointers.
Use existing BackendWorker._resolve_pointer/_escape_pointer_segment and loaders,
but reject invalid RFC6901 ~ escapes and noncanonical array indexes yourself before
those older helpers if needed. No source path (game directory) passed to writers.
Caller handles approved-display-field and TokenPolicy validation. Do not claim that
arbitrary strings from a third-party extractor are approved display text.

Return a dict {output_bytes:bytes,sidecar:dict,capabilities:dict}. Sidecar includes
relative_path, backend, exact SHA-256 of ORIGINAL source bytes, requested pointers
and backend locator data (addresses/groups/item indices/ctrl as applicable). No
absolute paths, source text dumps, third-party source or credentials in sidecar.
capabilities: memory_only True, third_party_write_api True, isolated_process_required
True, approved_display_text False. Actual parent tests will demonstrate isolation.

Common validation: resolve every requested pointer to the exact source_text.
Keep a deep copy of original document and construct an expected document by those
exact whole-leaf assignments ONLY. Call the real upstream write API. Require the
resulting parsed JSON to be exactly expected (type-preserving canonical JSON),
otherwise raise ValueError BACKEND_UNAPPROVED_DIFF. This is a comparison, NOT a
fallback writer. Do not return native-built bytes after a third-party failure.
No changes: return original bytes with no reformatting. Preserve original UTF-8 BOM
in outputs if present. All errors stable codes, never echo source/translation text.

## Stev actual memory API

Use BackendWorker._extract_stev(root,relative_path,document,decoded_source) ->
(records,caps), records text/locator/candidate_pointers. Accept a requested pointer
only if exactly one record with candidate_pointers == [pointer], locator.whole_string
True, merge_count is None or 1. Reject merged/ambiguous/substring cases.
Load root/jtpp.py via BackendWorker._load_module, instantiate Jr_Tpp with
{'ja':False,'ReadCode':[],'sumcode':[],'sptext':{}}.
Private `_Jr_Tpp__WriteFile(document,untrs,trsed,Dir,length,code)` RETURNS the new
document, mutating nested structures; Dir is tokens from the proven locator
address (strip '<basename>\\' and split '\\'), length=1, code from locator.
Do not call __del_marked_list or other cleanup. Record address/code in sidecar.

## SExtractor actual memory API

Use BackendWorker._extract_sextractor(...) to get fresh proven whole-string ctrl
snapshots. It configures common.ExVar and imports extract_RPGMV in this fresh
process. Require unique record candidate_pointers == [pointer], whole_string True.
Call actual extract_RPGMV.replaceOnceImp(document, selected_ctrls, translated_texts)
then replaceEndImp(document). These mutate document in memory. No main_extract or
filesystem APIs. Sidecar records requested pointer and exact ctrl. Broad/substring
rules rejected. Existing _configure_sextractor_vars keeps compression disabled.

## RPGMTL precise per-occurrence project mapper

The naive text-to-pointer index is ambiguous for duplicate text. Use a str subclass
`LocatedString` carrying its JSON pointer on each nonempty leaf. Recursively wrap
values of a parsed source document; keep dict keys and numbers unchanged.
Import only plugins.json.JSON (root on sys.path, no plugins.load). Set settings
json_rpgm_multiline False. For its READ call only, replace module.json with a
LOCAL proxy whose loads returns a deepcopy of the located document, dumps is stdlib
json.dumps. Restore module.json in finally before writing. Do NOT change stdlib
json.loads globally. This preserves real plugin traversal and proves each group
entry's actual source pointer; if a requested string loses pointer metadata (e.g.
unsupported combination), fail closed BACKEND_LOCATOR_UNSUPPORTED.

plugin.read(relative_path,source_utf8_bytes) -> groups [[label,source,...],...].
For each item after label, allocate a unique global ID even if text repeats:
project_strings['strings'][gid] = [str(source),None,1,0] (GloIndex ORI/TL/COUNT/COLOR).
project_strings['files'][relative_path] = groups in the exact original traversal,
with each source entry replaced by [gid,local_translation_or_None,1,0,modified_int]
(LocIndex ID/TL/LOCAL/IGNORED/MODIFIED). Labels remain strings, including empty/header
groups. Use the LocatedString pointer to assign ONLY requested local translations.
Set owner SimpleNamespace(CHILDREN_FILE_ID='::',strings={'ainiee':project_strings}).
Then call actual plugin.write('ainiee',relative_path,original_utf8_bytes) -> (bytes,bool).
Never broadcast through global translations. Require every requested pointer found
once; duplicate source strings at different pointers keep different local IDs.
CommonEvents virtual child groups require more owner state: explicitly refuse that
file for writes in this iteration. JSON/Items/Map/System/357 whole-leaf paths are
in scope when traversal and full semantic output comparison pass; no JS support
claim. Lost metadata or a real upstream writer defect is a refusal, not success.

Stdlib + existing local helper imports only. No tests by worker. Codex will run
real installed upstream code with synthetic DB/map/357/BOM/CRLF/Chinese paths and
validate same-source different translations, no game/upstream tree mutations,
and honest per-file unsupported results.
