# Explicit lineage proof for projects without a game id

Implement ONLY ModuleFolders/Service/GameProject/Lineage.py. Pure stdlib module,
no I/O, source inspection, mutation or execution. Read this contract and
tests/game_project/test_lineage_contract.py only. Tools read/write/edit ONLY;
NO grep/glob/shell/network/agents/execution or directory exploration. Codex owns
identity-report integration, persistence, CLI, GUI and independent testing.

API game_identity(value)->(canonical:str,reported:object), preserving existing
MigrationService semantics: bool/None/blank/nonpositive int/zero and signed
numeric string <=0 are unknown ('',''). Positive ints canonical str, reported
original int. Strings strip whitespace; signed numeric string parses int and
returns canonical positive decimal + reported stripped original string; other
nonempty strings except '0' are known, case sensitive. Non-int/str unknown.
Handle oversized numeric conversion ValueError as unknown, no silent bool/int match.

API build_confirmation(old_metadata,new_metadata,confirmed=False)->dict.
confirmed must be the EXACT boolean True, else raise ValueError with prefix
MIGRATION_LINEAGE_CONFIRMATION_REQUIRED. No name/title/fuzzy inference. Require:
- mappings; distinct nonempty stripped project_id (same -> MIGRATION_SAME_PROJECT)
- same nonempty stripped engine in rpgmaker-mv/rpgmaker-mz
- both target_language stripped or default zh-CN and exactly zh-CN
- source_manifest_hash 64 lowercase hex on BOTH sides
- if both game ids are known, they must match. A known mismatch, engine mismatch
  or language mismatch raises MIGRATION_PROJECT_MISMATCH. Missing/unsupported
  engines or manifest/project identity raises MIGRATION_LINEAGE_UNBOUND.

Return EXACT JSON-native keys:
schema_version:1, method:'user_confirmed_same_game', old_project_id,new_project_id,
old_source_manifest_hash,new_source_manifest_hash,engine,target_language:'zh-CN',
old_game_id,new_game_id (canonical strings, empty when unknown).
All values are immutable primitives; fresh dict per call; no timestamp, secrets,
paths or content text. This records an explicit user assertion, NOT automatic
identity proof; it never relaxes migration's location/source/token/revision guards.

API has_confirmation(old_metadata,new_metadata)->bool reads ONLY the new metadata
key migration_lineage. Return True iff that value is a dict exactly equal to a
fresh build_confirmation(old,new,confirmed=True). Reject extra/omitted/changed
fields, different manifest/project/known game id/engine/language. Invalid metadata
returns False rather than guessing. Never mutate input metadata. Keep focused
roughly <=130 lines; no framework. Tests use only synthetic metadata.
