# Central capability catalog contract

Implement only ModuleFolders/Infrastructure/GameAdapters/Capabilities.py.
Pure standard-library module, no imports of project code, no I/O or execution.
Codex handles registry, CLI, GUI, routing and acceptance. Only read/write/edit
tools; no grep/glob/shell/network/agents or directory exploration.

Expose capability_matrix() -> dict keyed by component id; every call returns
an independent deep copy of JSON-safe data. Expose route_support(backend,path)
-> dict {status, reason, ownership}; status supported/candidate_required/
unsupported; ownership whole_file_exclusive. Unknown backend raises ValueError
BACKEND_UNKNOWN. Never treat a static declaration as proof of tool availability
or of a particular document's successful write.

Catalog entries must have adapter_id, version, label, component_type, engines,
formats, supports, runtime_dependencies, validated_fixture_sets,
validated_game_profiles, write_ownership. supports values are only verified,
unsupported, unverified. Concrete entries:

- rpgmaker-native: version1.0.0, label 原生（默认）, engine_adapter,
  engines rpgmaker-mv/rpgmaker-mz, formats json, write_ownership json_pointer.
  standard_json/custom_json_profiles/event_script_profiles = verified,
  general_js_literals/image_ocr = unsupported; runtime_dependencies python.
  Fixture tests/game_project/test_adapter_acceptance.py and
  tests/game_project/test_event_literal_codec_acceptance.py; game profiles
  selenoxia-test-0.141 (only this title is real-game tested).
- js-literal: version acorn-8.19.0, label 指定 JS 文字, text_component,
  same engines, formats js, write_ownership utf8_byte_span.
  explicit_object_profiles/scoped_object_profiles verified,
  general_js_literals unsupported; runtime_dependencies node/acorn.
  Fixture tests/game_project/test_js_acceptance.py and
  tests/game_project/test_js_scope_acceptance.py; same game profile.
- image-region: version1, label 已确认图片区域, resource_component,
  same engines, formats png/png_/rpgmvp, write_ownership image_region_plan.
  confirmed_regions/redraw/encrypted_png verified; automatic_visual_quality
  unsupported; runtime_dependencies qt/font; fixture
  tests/game_project/test_image_acceptance.py; same game profile.
- stev: version 7bbb06be33f5968f0723a5200a150d895d4fa5fb (jtpp baseline),
  label StevExtraction, document_backend, same engines, formats json,
  write_ownership whole_file_exclusive; standard_json/occurrence_translation/
  mz_choices/mz357 verified, general_js_literals unsupported,
  arbitrary_custom_fields unverified. runtime_dependencies python/jtpp.py.
- rpgmtl: version0fa346b020e439fd392027f735107a283c9836d9,
  label RPGMTL, document_backend, same engines, formats json,
  same ownership/support flags as stev plus common_events unsupported.
  runtime_dependencies python/plugins.json.
- sextractor: version8d8d976fd04ae54e7c677705af937273d04a376a,
  label SExtractor, document_backend, same engines, formats json,
  same ownership/support flags as stev. runtime_dependencies
  python/extract_RPGMV. For ALL 3 document_backends fixtures only
  tests/game_project/test_backend_write_acceptance.py and
  tests/game_project/test_event_backend_acceptance.py; real-game profiles [].

route_support only supports route IDs native/stev/rpgmtl/sextractor, NOT
js-literal/image-region. A file path must be a nonempty safe relative string;
normalize backslashes and casefold, reject absolute/drive/UNC, empty/dot/dotdot
components, colon, ASCII controls, trailing dot/space. Only .json files accepted
for these routes. Native JSON status supported reason native_json. Other JSON
candidate_required reason exact_candidate_proof_required. RPGMTL rejects a
basename CommonEvents.json case-insensitively with reason common_events_virtual
and a path with no directory with reason document_path_required. Invalid path or
non-JSON reason unsupported_document. No filesystem reads or claims that a
candidate can be skipped. Keep implementation focused, no plugin framework.
