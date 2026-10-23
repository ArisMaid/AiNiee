# Native MV/MZ adapter contract (v1)

Use the foundation Models, PathGuard and AdapterProtocol interfaces. Do not change
these interfaces or supervisor-owned tests. Keep code stdlib except optional YAML
loading through safe_load. No execution of source scripts, deletion or network.

Files under Infrastructure/GameAdapters/RpgMaker:

- Detector.py: detect_game(source: str|Path) -> dict. Return absolute root,
  data_dir (relative path), js_dir, engine ('rpgmaker-mv'|'rpgmaker-mz'),
  engine_version, locale, game_title, game_id. Support both root/data and www/data;
  require System.json, corresponding core JS and index.html/package evidence.
  Ambiguous multiple valid roots raises ValueError. EXE input means parent dir.
- JsonExtractor.py: extract_game(source, profile=None) -> ExtractionResult.
  Include all data/*.json in files metadata (relative_path, sha256, size,
  encoding), but extract only explicitly approved standard fields or profile
  selectors. Stable unit IDs via uuid5(relative_path + locator + role); distinct
  occurrences remain distinct unless a choice branch is intentionally linked.
  Every occurrence has relative path, {'pointer': RFC6901 pointer}, expected value
  hash, and a unique occurrence_id. Include scene and nearby speaker metadata.
  stats: data_json_count, map_count, code_counts (string code keys), unit_count.
  Recognized-file parse failure -> error Issue, not silent skip. Catch file errors
  with path in issue. Resource names/IDs/formulas/editor names never auto-extract.
- EventRules.py: pure helpers for known event command lists; 401/405 one unit per
  original text line; 101 MZ speaker field as separate speaker unit; 102 choices
  link to matching 402 text parameter in same command list at matching indent and
  branch index until 404. Nested choices tracked independently. 320/324/325 only
  text parameter 1. Skip 108/408/657 comments, 111 conditions, 355/655 scripts,
  356/357 parameters unless explicit per-command profile specifies text fields.
  Unknown script/plugin instructions yield summary warning candidates, not
  thousands of identical diagnostics; do not mark them as translated.
- JsonPatcher.py: patch_json(original: bytes, replacements:
  list[tuple[Occurrence,str]]) -> bytes. Refuse duplicate/overlapping pointers,
  path traversal, missing fields, non-string target, old-value hash mismatch.
  Return original bytes if no logical change. On changes preserve BOM if present,
  dump UTF-8 ensure_ascii=False, reparse and assert all semantic differences are
  exactly the listed pointers. Array length/types/null entries preserved. Include
  resolve_pointer(document,pointer) and semantic_differences(a,b)->set[str].
- ProfileLoader.py: load_profile(path)->dict with safe YAML/JSON; validate known
  schema_version=1, id, engine; selectors restricted to '/' segments with '*' at
  current level. reject embedded executable YAML, absolute/traversal source file
  paths. profile json_rules entries: id,file,selector,value_type='string',role,
  evidence_status='verified' or pending. Only verified rules extract writable
  units; pending rules are candidate warnings. Iterate matching nodes via
  select_values(document,selector)->list[(RFC6901 pointer,value)].

Standard DB text whitelist:
Actors: name,nickname,profile. Classes: name. Items/Weapons/Armors:
name,description. Skills: name,description,message1,message2. Enemies: name.
States: name,message1,message2,message3,message4. System: gameTitle,currencyUnit,
terms string leaves, skillTypes,weaponTypes,armorTypes,equipTypes,elements labels.
Maps: displayName and events[].pages[].list. CommonEvents[].list and
Troops[].pages[].list recognized commands. MapInfos, Tilesets, Animations and
unknown JSON get no generic text recursion. note fields, switch/variable names,
file names, resources and numeric/logic values remain untouched.

Registry.py (under Infrastructure/GameAdapters, not RpgMaker):
RpgMakerAdapter with adapter_id='rpgmaker-native', version='1.0.0',
probe(source), capabilities(), extract(source,profile=None). AdapterRegistry()
register(adapter), get(adapter_id), list(), detect(source). Reject duplicate IDs;
default constructor registers native adapter. Do not register unimplemented tools
as functional adapters.

The native adapter initially supports JSON only; JS and current game profile are
separately integrated by Codex. Report capability flags truthfully. Never use
runtime engine loads, regex on raw JSON or source->translation global replace.
