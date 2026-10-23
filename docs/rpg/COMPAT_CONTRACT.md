# Compatibility extraction contract

This contract covers the read/extraction comparison API. Separate memory-only
writer integrations and their validation are described in BACKEND_EVIDENCE.md.
Extraction candidates never grant write authority or merge backend ownership.

## BackendWorker.py
Standalone stdlib stdin/stdout JSON worker. Request: backend (stev/rpgmtl/sextractor),
backend_root absolute path, relative_path validated safe JSON path, source string.
Return {ok:true,backend,records:[{text,locator,candidate_pointers}],capabilities:{...}}.
Capture incidental upstream stdout with contextlib.redirect_stdout to StringIO,
never contaminate protocol output. Exceptions produce ok:false,error with no dump
of source content. All work is memory only; never call ReadGame/InjectGame,
mainExtract or CLI applications, no deletions, archives or auto plugins loaded.

Stev: import exact trusted root/jtpp.py using importlib.util, construct Jr_Tpp with
ja=False, ReadCode=[],sumcode=[],sptext={} then call _Jr_Tpp__ReadFile on parsed JSON
and basename. Flush its pending _Jr_Tpp__tempdata once if _Jr_Tpp__sumlen>0.
Convert row[2] backslash addresses (remove basename prefix) into escaped pointer,
strip optional U+200B merge count; require pointer resolves to same string. Report
nonwhole-string candidates without a writable pointer. Do not use ProgramData or
whole-game read/write routines and their spreadsheet/plugin side effects.

RPGMTL: add trusted root to sys.path then import plugins.json.JSON only; instantiate,
set_settings({'json_rpgm_multiline':False}), owner SimpleNamespace(CHILDREN_FILE_ID='::').
Call read(relative_path, source encoded UTF8). Groups [label, strings...]. Record
locator {group_index,item_index}; source-leaf exact text matches become
candidate_pointers. Never invent a unique pointer for duplicates or merged text.
No automatic writes. Report common-event virtual groups as candidate records.

Large candidate arrays may use the additive shared pool schema:

```json
{"pointer_pool_schema":1,"candidate_pointer_groups":{"g0":["/1/name","/2/name"]},
 "records":[{"text":"example","locator":{},"candidate_pointer_group":"g0"}]}
```

Small arrays keep the legacy candidate_pointers field. A referenced record has
no inline candidate_pointers. `ExtractionPointerPool.pointer_lists(result)`
validates version, groups and references and returns borrowed arrays in record
order, without per-reference expansion. All candidate addresses remain available;
multiple distinct pointers remain ambiguous. Invalid or mixed layouts reject.
The existing 16MB response bound is unchanged. RPGMTL shares source index lists
internally before packing, avoiding quadratic allocation as well as wire size.

SExtractor: add trusted root/src to sys.path then import extract_RPGMV and common.
Set common.ExVar.regDic={'search':r'^<[^>]+>([\s\S]+)$'}, extractKey='name,description,nickname,profile',
structure='',decrypt='',nameList=[], no file side effects. Invoke parseImp on
parsed JSON, callback dealOnce(text,ctrl) records text + deep-copied ctrl and returns
True. listCtrl is also owned by upstream; verify actual call behavior. ctrl.pos
contains node path + offsets including artificial 9-char header; expose raw ctrl
and resolve complete string pointer when span is exactly its entire value.
If this limited API has additional required attributes, inspect ONLY listed files
and set explicit safe defaults. No wholesale main_extract import or global GUI.

Input/output bounded 16MB; require source JSON. All capabilities must say
write=false, extraction_only=true. Broad extractions are candidates, not approved
display text. No backend union or automatic ownership promotion.

## CompatibilityBridge.py
`extract_document(backend, relative_path, payload:bytes, work_root, backend_root)`
validates safe path, rejects non-JSON, creates a UUID work subdirectory without
deleting anything, saves request/result via safe atomic_write, subprocess runs
sys.executable BackendWorker.py shell=False timeout=60, isolated cwd, UTF8 pipes.
Allow basic OS PATH/SystemRoot/WINDIR and Python no-user-site; no inherited API
keys/provider config. Use project modules via explicit trusted repo PYTHONPATH.
Upstream dirs must exist and have expected file jtpp.py / plugins/json.py /
src/extract_RPGMV.py. Errors are actionable. Return decoded result or ValueError.
Do not import upstream libs in parent. No real source root parameter is needed.

## CoverageComparison.py
`compare_extractions(native_units, backend_result, relative_path)` returns counts,
native_only:[{unit_id,pointer}], backend_only:[{record_index,candidate_pointers}],
overlap, ambiguous:[...]. Native pointers are authoritative approved occurrences.
Compare exact pointers when known; multiple candidate pointers ALWAYS ambiguous,
do not count raw string equality as approved coverage. No mutation, no IO.
With pooled input, the report also carries pointer_pool_schema and shared
candidate_pointer_groups; ambiguous/backend_only rows use candidate_pointer_group
and candidate_pointer_count. Reports do not duplicate the same large array for
each record. Consumers can inspect every logical candidate through that group.

Relevant exact upstream files you may read (NO directory grep):
StevExtraction/jtpp.py
work/vendor/RPGMTL/plugins/json.py
work/vendor/RPGMTL/plugins/__init__.py
work/vendor/SExtractor/src/extract_RPGMV.py
work/vendor/SExtractor/src/extract_TXT.py
work/vendor/SExtractor/src/common.py
work/vendor/SExtractor/src/var_extract.py
You may also read PathGuard.py and Models.py at their exact existing paths.
# 0.10 执行参数防护增量

物理工程格式保持不变，旧工程可读。提取缓存算法改为
`rpg-extraction-event-write-guard-v2`，写入计划算法改为
`rpg-build-event-write-guard-v5`；旧算法未完成的作业拒绝恢复，须新建一次提取或构建。
旧库若含普通字符串形式的事件脚本译文，构建会以 UNSAFE_EVENT_STRING_TARGET 拒绝。
现有受限事件字符串编解码和显示参数保持，详见 COMMAND_AUDIT_EVIDENCE.md。
