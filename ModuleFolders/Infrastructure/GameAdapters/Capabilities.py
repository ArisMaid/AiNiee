"""Pure, static capability catalog and route-support predicate.

This module contains no project imports, filesystem access, or execution. It is
a declaration of what has been verified by fixtures; a declaration is never
proof that an external tool is available or that a document was written.
"""

import copy


_ROUTE_BACKENDS = ("native", "stev", "rpgmtl", "sextractor")

_OWNERSHIP = "whole_file_exclusive"

_RPGMAKER_ENGINES = ["rpgmaker-mv", "rpgmaker-mz"]
_SELENOXIA_PROFILE = ["selenoxia-test-0.141"]
_DOCUMENT_FIXTURES = [
    "tests/game_project/test_backend_write_acceptance.py",
    "tests/game_project/test_event_backend_acceptance.py",
]

_CATALOG = {
    "rpgmaker-native": {
        "adapter_id": "rpgmaker-native",
        "version": "1.0.0",
        "label": "原生（默认）",
        "component_type": "engine_adapter",
        "engines": list(_RPGMAKER_ENGINES),
        "formats": ["json"],
        "supports": {
            "standard_json": "verified",
            "custom_json_profiles": "verified",
            "event_script_profiles": "verified",
            "general_js_literals": "unsupported",
            "image_ocr": "unsupported",
        },
        "runtime_dependencies": ["python"],
        "validated_fixture_sets": [
            "tests/game_project/test_adapter_acceptance.py",
            "tests/game_project/test_event_literal_codec_acceptance.py",
        ],
        "validated_game_profiles": list(_SELENOXIA_PROFILE),
        "write_ownership": "json_pointer",
    },
    "js-literal": {
        "adapter_id": "js-literal",
        "version": "acorn-8.19.0",
        "label": "指定 JS 文字",
        "component_type": "text_component",
        "engines": list(_RPGMAKER_ENGINES),
        "formats": ["js"],
        "supports": {
            "explicit_object_profiles": "verified",
            "scoped_object_profiles": "verified",
            "scoped_static_fragments": "verified",
            "general_js_literals": "unsupported",
        },
        "runtime_dependencies": ["node", "acorn"],
        "validated_fixture_sets": [
            "tests/game_project/test_js_acceptance.py",
            "tests/game_project/test_js_scope_acceptance.py",
        ],
        "validated_game_profiles": list(_SELENOXIA_PROFILE),
        "write_ownership": "utf8_byte_span",
    },
    "image-region": {
        "adapter_id": "image-region",
        "version": "1",
        "label": "已确认图片区域",
        "component_type": "resource_component",
        "engines": list(_RPGMAKER_ENGINES),
        "formats": ["png", "png_", "rpgmvp"],
        "supports": {
            "confirmed_regions": "verified",
            "redraw": "verified",
            "encrypted_png": "verified",
            "automatic_visual_quality": "unsupported",
        },
        "runtime_dependencies": ["qt", "font"],
        "validated_fixture_sets": [
            "tests/game_project/test_image_acceptance.py",
        ],
        "validated_game_profiles": list(_SELENOXIA_PROFILE),
        "write_ownership": "image_region_plan",
    },
    "stev": {
        "adapter_id": "stev",
        "version": "7bbb06be33f5968f0723a5200a150d895d4fa5fb",
        "label": "StevExtraction",
        "component_type": "document_backend",
        "engines": list(_RPGMAKER_ENGINES),
        "formats": ["json"],
        "supports": {
            "project_directory": "verified",
            "program_data_bridge": "verified",
            "empty_translation": "unsupported",
            "standard_json": "verified",
            "occurrence_translation": "verified",
            "mz_choices": "verified",
            "mz357": "verified",
            "general_js_literals": "unsupported",
            "arbitrary_custom_fields": "unverified",
        },
        "runtime_dependencies": ["python", "jtpp.py", "config.yaml", "pandas", "openpyxl", "chardet", "PyYAML"],
        "validated_fixture_sets": list(_DOCUMENT_FIXTURES)+[
            "tests/game_project/test_stev_project_entry.py",
            "tests/game_project/test_stev_project_effects.py",
        ],
        "validated_game_profiles": [],
        "write_ownership": "whole_file_exclusive",
    },
    "rpgmtl": {
        "adapter_id": "rpgmtl",
        "version": "0fa346b020e439fd392027f735107a283c9836d9",
        "label": "RPGMTL",
        "component_type": "document_backend",
        "engines": list(_RPGMAKER_ENGINES),
        "formats": ["json", "js"],
        "supports": {
            "standard_json": "verified",
            "occurrence_translation": "verified",
            "mz_choices": "verified",
            "mz357": "verified",
            "general_js_literals": "unsupported",
            "arbitrary_custom_fields": "unverified",
            "common_events": "verified",
            "explicit_js_literals": "verified",
            "static_template_parts": "unsupported",
        },
        "runtime_dependencies": ["python", "plugins.json", "plugins.javascript", "node", "acorn"],
        "validated_fixture_sets": list(_DOCUMENT_FIXTURES)+[
            "tests/game_project/test_rpgmtl_js_acceptance.py",
            "tests/game_project/test_js_output_audit.py",
        ],
        "validated_game_profiles": [],
        "write_ownership": "whole_file_exclusive",
    },
    "sextractor": {
        "adapter_id": "sextractor",
        "version": "8d8d976fd04ae54e7c677705af937273d04a376a",
        "label": "SExtractor",
        "component_type": "document_backend",
        "engines": list(_RPGMAKER_ENGINES),
        "formats": ["json"],
        "supports": {
            "main_entrypoint": "verified",
            "standard_json": "verified",
            "occurrence_translation": "verified",
            "mz_choices": "verified",
            "mz357": "verified",
            "general_js_literals": "unsupported",
            "arbitrary_custom_fields": "unverified",
        },
        "runtime_dependencies": ["python", "extract_RPGMV", "src/main_extract.py", "src/main_extract_json.py",
            "src/engine.ini", "PyQt5.QtCore", "pandas", "rapidjson"],
        "validated_fixture_sets": list(_DOCUMENT_FIXTURES)+[
            "tests/game_project/test_sextractor_array_fields.py",
            "tests/game_project/test_sextractor_main_entry.py",
            "tests/game_project/test_sextractor_main_effects.py",
        ],
        "validated_game_profiles": [],
        "write_ownership": "whole_file_exclusive",
    },
}


def capability_matrix():
    """Return an independent deep copy of the static capability catalog."""
    return copy.deepcopy(_CATALOG)


def _normalize_document_path(path):
    """Return a normalized safe relative JSON/JS path, or None when invalid."""
    if not isinstance(path, str) or not path:
        return None

    normalized = path.replace("\\", "/")
    if not normalized:
        return None

    # Absolute paths, UNC paths, and any drive/stream colon are rejected.
    if normalized.startswith("/") or ":" in normalized:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        return None

    folded = normalized.casefold()
    components = folded.split("/")
    for component in components:
        if not component or component in (".", ".."):
            return None
        if component.endswith(".") or component.endswith(" "):
            return None

    if not folded.endswith((".json",".js")):
        return None
    return folded


def _route_result(status, reason):
    return {
        "status": status,
        "reason": reason,
        "ownership": _OWNERSHIP,
    }


def route_support(backend, path):
    """Describe route eligibility for a relative document path.

    This predicate is static: it never reads the filesystem, never claims a
    candidate can be skipped, and never treats a catalog declaration as proof
    that an external tool or write will succeed.
    """
    if backend not in _ROUTE_BACKENDS:
        raise ValueError("BACKEND_UNKNOWN")

    normalized = _normalize_document_path(path)
    if normalized is None:
        return _route_result("unsupported", "unsupported_document")

    if normalized.endswith('.js'):
        if backend=='native':return _route_result('supported','native_explicit_js')
        if backend!='rpgmtl':return _route_result('unsupported','js_backend_unverified')
        if normalized=='js/plugins.js' or normalized.endswith('/js/plugins.js'):
            return _route_result('unsupported','plugins_registry_requires_native_profile')
        return _route_result('candidate_required','exact_js_span_and_ast_proof_required')

    if backend == "rpgmtl":
        if "/" not in normalized:
            return _route_result("unsupported", "document_path_required")
    if backend=='stev' and not normalized.startswith('data/'):
        return _route_result('unsupported','project_data_directory_required')

    if backend == "native":
        return _route_result("supported", "native_json")
    return _route_result("candidate_required", "exact_candidate_proof_required")
