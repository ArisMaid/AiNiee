# Native per-document extraction seam

Worker scope ONLY ModuleFolders/Infrastructure/GameAdapters/RpgMaker/JsonExtractor.py.
Read/write/edit only. NO grep, glob, shell, execution, network, agents or directory
exploration. Codex owns journal/service/Registry/JS integration and independent
tests. Read this contract and tests/game_project/test_extraction_document.py.
Relevant existing code is entirely in the allowed JsonExtractor.py; keep helpers
below _table_specs unchanged. Do not inspect private work projects or credentials.

Refactor without changing existing uncached output. Add:

extract_document(relative_path, payload, settings=None) -> ExtractionResult

- Pure byte parser: no filesystem reads/writes, engine probe or subprocess. Accept
  bytes and a validated profile mapping (possibly {} or None); never mutate inputs.
  Reject other payload/settings types and unsafe paths clearly. Path is safe
  relative .json with Windows slashes accepted; normalize to /. Reject absolute,
  drive/UNC/colon, empty/dot/dotdot components, ASCII controls, trailing dot/space.
- settings is already validated by extract_game. No load_profile path allowed.
- Same standard fields/events/profile rules/literal codecs and stable IDs.
- One file metadata record with relative_path, sha256, size, encoding. Parse error
  retains encoding='', emits same json_parse_error message/path, units empty.
- Per-file stats contain data_json_count=1, map_count (0/1), code_counts,
  unsupported_commands, unit_count, profile_excluded_count/profile_exclusions.
- Per-file issues include actual parse/literal issues. Pending-profile warnings and
  unsupported_command_candidate summaries remain GLOBAL, emitted once by extract_game.

Extend extract_game(source, profile=None, progress=None, document_cache=None).
Its source detection/profile validation, progress callbacks, units/files order,
issue order and final stats MUST remain exactly compatible. Read each payload
via safe_join as before. If document_cache is provided, invoke:

document_cache(relative_path, payload_bytes, validated_settings, compute)

where compute() returns extract_document(relative_path,payload,settings). Use the
returned ExtractionResult and aggregate per-file counters/exclusions/issues. A
cache owns freshness and persistence; the extractor must not save anything.
Unknown return type rejects. No-cache calls behave exactly as before, including
file read error reporting. With cache, a source read error must fail immediately
with EXTRACTION_SOURCE_READ_FAILED so an ordered journal cannot silently skip a
missing input. Pending rules/global summary order unchanged. Progress calls stay
before each file with zero-based done, plus final complete.

Do not change filtering, source text, tokens, event handling, stat key names,
formatting or encodings. No unrelated framework, feature expansion or tests edits.
Export both extract_game and extract_document. Codex will compare pre-refactor
golden output and cold/warm results and execute all existing regressions.
