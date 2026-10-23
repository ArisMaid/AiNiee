"""Real two-process SExtractor ``main_extract`` / ``main_extract_json`` pipeline.

This bridge is the default SExtractor write path.  It never imports the
vendored extractor into the GUI process and it never falls back to the
memory-only :mod:`BackendWriters` implementation: extraction and import are two
separate, freshly started ``BackendWorker`` subprocesses, each of which calls
the actual upstream ``main_extract_json.mainExtractJson`` entry point.

The parent validates the request (pointer/source guards, exact expected
document) and both worker responses; each phase validates its own inputs too.
The phases exchange source,
captured ``engine.ini`` bytes, the exact validated changes and the real export
bytes; a phase child owns a private ``main`` directory next to its empty cwd
and is only allowed to create the declared upstream output there.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from ModuleFolders.Service.GameProject.PathGuard import atomic_write, safe_join

from . import BackendWorker as _backend_worker
from . import CompatibilityBridge as _compatibility
from .BackendWriters import (
    MAX_OUTPUT_BYTES,
    MAX_SOURCE_BYTES,
    WriterError,
    _assert_expected,
    _decode_source,
    _normalize_changes,
    _sextractor_owner_key,
    _unique_record,
    _walk_pointer,
)

__all__ = [
    "ALLOWED_FILES",
    "CAPABILITIES",
    "ENTRYPOINT",
    "MODULE_FILES",
    "SOURCE_FILES",
    "build_plan",
    "encode_translations",
    "rewrite_document",
    "split_para_sentinel",
]

ENTRYPOINT = "main_extract_json.mainExtractJson -> main_extract.mainExtract"

CAPABILITIES = {
    "main_entrypoint": True,
    "memory_only": False,
    "third_party_write_api": True,
    "isolated_process_required": True,
    "approved_display_text": False,
}

# Exactly the real main/JSON/helper engine source dependencies.  Tests copy this
# list into an isolated SDK directory, so nothing else may be required.
SOURCE_FILES = (
    "common.py",
    "engine.ini",
    "extract_RPGMV.py",
    "extract_TXT.py",
    "helper_read.py",
    "helper_text.py",
    "helper_write.py",
    "main_extract.py",
    "main_extract_json.py",
    "main_extract_part.py",
    "var_extract.py",
)

MODULE_FILES = {name[:-3]: name for name in SOURCE_FILES if name.endswith(".py")}

_ALLOWED_EXTRACT = frozenset(
    {
        "src/engine.ini",
        "document/input.json",
        "document/ctrl/all.orig.json",
    }
)
_ALLOWED_IMPORT = frozenset(
    set(_ALLOWED_EXTRACT)
    | {
        "document/ctrl/all.trans.json",
        "document/new/input.json",
    }
)
ALLOWED_FILES = {"extract": _ALLOWED_EXTRACT, "import": _ALLOWED_IMPORT}

MAX_IO_BYTES = getattr(_compatibility, "MAX_IO_BYTES", 16 * 1024 * 1024)
MAX_REQUEST_BYTES = MAX_IO_BYTES
MAX_CHANGES = 200_000
MAX_RECORDS = 1_000_000
HEADER_LEN = 9
BOM_UTF8 = codecs.BOM_UTF8
_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


# ---------------------------------------------------------------------------
# small shared helpers (also imported by the phase worker)
# ---------------------------------------------------------------------------
def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _decode_b64(value, label, limit):
    if not isinstance(value, str):
        raise ValueError(f"BACKEND_PIPELINE_INVALID: {label}")
    if len(value) > (limit * 4) // 3 + 4096:
        raise ValueError(f"BACKEND_PIPELINE_INVALID: {label}")
    try:
        data = base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        raise ValueError(f"BACKEND_PIPELINE_INVALID: {label}") from None
    if len(data) > limit:
        raise ValueError(f"BACKEND_PIPELINE_INVALID: {label}")
    return data


def _read_bounded(path, limit, code="BACKEND_PIPELINE_INVALID", label="file"):
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError:
        raise ValueError(f"{code}: {label}") from None
    if len(data) > limit:
        raise ValueError(f"{code}: {label}")
    return data


def _norm(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def _is_reparse(info):
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE_FLAG)


def _invalid(detail=""):
    raise ValueError("BACKEND_PIPELINE_INVALID" + (f": {detail}" if detail else ""))


def _side_effect(detail=""):
    raise ValueError("BACKEND_SIDE_EFFECT" + (f": {detail}" if detail else ""))


def _default_extract_keys():
    raw = getattr(
        _backend_worker, "SEXTRACTOR_EXTRACT_KEY", "name,description,nickname,profile"
    )
    return [key for key in str(raw).split(",") if key]


# ---------------------------------------------------------------------------
# deterministic request-driven plan shared by parent and both phases
# ---------------------------------------------------------------------------
def _event_literal_pointers(document, requested):
    literals = set()
    for index, change in enumerate(requested):
        if list(change.tokens[-2:]) != ["parameters", "4"]:
            continue
        parent = _walk_pointer(document, change.tokens[:-2], index)
        if not isinstance(parent, dict) or parent.get("code") != 122:
            continue
        values = parent.get("parameters")
        if (
            type(parent.get("code")) is not int
            or not isinstance(values, list)
            or len(values) != 5
            or any(type(value) is not int for value in values[:4])
            or values[0] != values[1]
            or values[0] <= 0
            or values[2:4] != [0, 4]
        ):
            raise WriterError("BACKEND_LOCATOR_UNSUPPORTED", "event literal assignment")
        from ModuleFolders.Domain.GameProject.EventLiteralCodec import decode_literal

        try:
            decode_literal(change.source_text)
            decode_literal(change.text)
        except ValueError:
            raise WriterError(
                "BACKEND_LOCATOR_UNSUPPORTED",
                "event expression is not a string literal",
            ) from None
        literals.add(change.pointer)
    return literals


def split_para_sentinel(document, *text_groups):
    """Return a deterministic ASCII alphanumeric separator absent from strings."""
    values = []

    def walk(node):
        if isinstance(node, str):
            if node:
                values.append(node)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            for child in node.values():
                walk(child)

    walk(document)
    for group in text_groups:
        for value in group:
            if isinstance(value, str) and value:
                values.append(value)
    for index in range(100_000):
        candidate = f"AiNieeSplitV20{index:05d}"
        if all(candidate not in value for value in values):
            return candidate
    raise ValueError("BACKEND_PIPELINE_INVALID: no unused split separator")


def build_plan(document, changes):
    """Validate the change list and derive exact request-driven upstream rules."""
    expected = copy.deepcopy(document)
    requested = _normalize_changes(changes, document, expected)
    extra_keys = set()
    for index, change in enumerate(requested):
        owner = _sextractor_owner_key(document, change.tokens, index)
        if owner is not None:
            extra_keys.add(owner)
    extract_key = ",".join(sorted(set(_default_extract_keys()) | extra_keys))
    event_literals = _event_literal_pointers(document, requested)
    sentinel = split_para_sentinel(document, [change.text for change in requested])
    return {
        "requested": requested,
        "expected": expected,
        "extract_key": extract_key,
        "event_literals": event_literals,
        "sentinel": sentinel,
    }


def encode_translations(translations):
    """Serialise the index-aligned translation vector exactly once."""
    return json.dumps(translations, ensure_ascii=False).encode("utf-8")


def _wire_changes(requested):
    return [
        {
            "pointer": change.pointer,
            "source_text": change.source_text,
            "text": change.text,
        }
        for change in requested
    ]


# ---------------------------------------------------------------------------
# upstream snapshot (parent side; read-only, no imports)
# ---------------------------------------------------------------------------
def _snapshot_upstream(root):
    root = Path(os.path.abspath(os.fspath(root)))
    try:
        source_dir = safe_join(root, "src", must_exist=True)
    except ValueError:
        raise ValueError("BACKEND_UPSTREAM_MISSING: src") from None
    if not source_dir.is_dir():
        raise ValueError("BACKEND_UPSTREAM_MISSING: src")
    files = []
    hashes = {}
    config = None
    entrypoint = None
    for name in SOURCE_FILES:
        try:
            path = safe_join(source_dir, name, must_exist=True)
        except ValueError:
            raise ValueError(f"BACKEND_UPSTREAM_MISSING: src/{name}") from None
        if not path.is_file():
            raise ValueError(f"BACKEND_UPSTREAM_MISSING: src/{name}")
        try:
            info = os.lstat(path)
        except OSError:
            raise ValueError(f"BACKEND_UPSTREAM_MISSING: src/{name}") from None
        if _is_reparse(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError(f"BACKEND_UPSTREAM_MISSING: src/{name}")
        data = _read_bounded(
            path, MAX_IO_BYTES, "BACKEND_UPSTREAM_MISSING", f"src/{name}"
        )
        digest = _sha256(data)
        files.append({"path": name, "size": len(data), "sha256": digest})
        hashes[name] = digest
        if name == "engine.ini":
            config = data
        elif name == "main_extract.py":
            entrypoint = digest
    if config is None or entrypoint is None:
        raise ValueError("BACKEND_UPSTREAM_MISSING: src")
    return {
        "root": root,
        "src": source_dir,
        "files": files,
        "hashes": hashes,
        "config": config,
        "config_sha256": _sha256(config),
        "entrypoint_sha256": entrypoint,
    }


def _require_upstream_unchanged(upstream):
    for row in upstream["files"]:
        try:
            path = safe_join(upstream["src"], row["path"], must_exist=True)
            data = _read_bounded(
                path, MAX_IO_BYTES, "BACKEND_SIDE_EFFECT", row["path"]
            )
        except ValueError:
            _side_effect("upstream source changed")
        if len(data) != row["size"] or _sha256(data) != row["sha256"]:
            _side_effect("upstream source changed")


# ---------------------------------------------------------------------------
# phase execution
# ---------------------------------------------------------------------------
def _write_artifact(case_dir, name, data):
    atomic_write(case_dir / name, data, overwrite=True)


def _failure_code(error):
    message = str(error)
    for code in (
        "BACKEND_SIDE_EFFECT",
        "BACKEND_PIPELINE_INVALID",
        "BACKEND_DEPENDENCY_MISSING",
        "BACKEND_OUTPUT_TOO_LARGE",
        "BACKEND_OUTPUT_LIMIT",
        "BACKEND_UPSTREAM_MISSING",
        "BACKEND_UNAPPROVED_DIFF",
        "BACKEND_LOCATOR_UNSUPPORTED",
        "BACKEND_POINTER_INVALID",
        "BACKEND_SOURCE_TEXT_MISMATCH",
        "JOB_CANCELLED",
    ):
        if code in message:
            return code
    return type(error).__name__


def _write_failure(case_dir, operation, error):
    payload = {
        "ok": False,
        "operation": "extract" if operation.endswith("extract") else "import",
        "error_code": _failure_code(error),
    }
    try:
        _write_artifact(
            case_dir,
            f"{operation}-error.json",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
    except Exception:
        # Failure evidence must not replace the original error or cancellation.
        pass


def _run_phase(case_dir, phase_dir, operation, base_request):
    try:
        phase_dir.mkdir()
    except OSError:
        raise ValueError("BACKEND_WORK_ROOT_INVALID: phase directory") from None
    run_dir = phase_dir / "cwd"
    try:
        run_dir.mkdir()
    except OSError:
        raise ValueError("BACKEND_WORK_ROOT_INVALID: phase cwd") from None
    request = dict(base_request)
    request["operation"] = operation
    request["phase_root"] = str(phase_dir)
    raw = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("BACKEND_REQUEST_TOO_LARGE")
    _write_artifact(case_dir, f"{operation}-request.json", raw)
    try:
        completed = _compatibility._run_worker(raw, run_dir, "sextractor")
    except BaseException as error:
        _write_failure(case_dir, operation, error)
        raise
    stdout = getattr(completed, "stdout", b"") or b""
    if isinstance(stdout, str):
        stdout = stdout.encode("utf-8")
    if len(stdout) > MAX_REQUEST_BYTES:
        raise ValueError("BACKEND_RESPONSE_TOO_LARGE")
    _write_artifact(case_dir, f"{operation}-result.json", stdout)
    try:
        result = _compatibility._decode_result(stdout, completed, "sextractor")
    except BaseException as error:
        _write_failure(case_dir, operation, error)
        raise
    if not isinstance(result, dict):
        _invalid("response type")
    return result


# ---------------------------------------------------------------------------
# response validation (parent side)
# ---------------------------------------------------------------------------
def _validate_manifest_schema(rows, operation):
    if not isinstance(rows, list):
        _invalid("manifest")
    expected = ALLOWED_FILES[operation]
    manifest = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "size", "sha256"}:
            _invalid("manifest row")
        path = row["path"]
        if not isinstance(path, str) or path not in expected:
            _side_effect("manifest path")
        if path in manifest:
            _invalid("manifest duplicate")
        size = row["size"]
        digest = row["sha256"]
        if type(size) is not int or size < 0 or size > MAX_IO_BYTES:
            _invalid("manifest size")
        if not isinstance(digest, str) or _HEX64.fullmatch(digest) is None:
            _invalid("manifest hash")
        manifest[path] = row
    if set(manifest) != expected:
        _invalid("manifest missing")
    return manifest


def _validate_modules(rows, upstream):
    if not isinstance(rows, list):
        _invalid("modules")
    modules = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"name", "path", "sha256"}:
            _invalid("module row")
        name = row["name"]
        path = row["path"]
        digest = row["sha256"]
        if not isinstance(name, str) or name not in MODULE_FILES or name in modules:
            _invalid("module name")
        if path != MODULE_FILES[name]:
            _invalid("module path")
        if not isinstance(digest, str) or digest != upstream["hashes"].get(MODULE_FILES[name]):
            _invalid("module hash")
        modules[name] = row
    if set(modules) != set(MODULE_FILES):
        _invalid("module set")
    return modules


def _validate_common_phase(response, operation, context, main_dir):
    if response.get("backend") != "sextractor":
        _invalid("backend")
    if response.get("operation") != operation:
        _invalid("operation")
    pid = response.get("pid")
    if type(pid) is not int or pid <= 0 or pid == os.getpid():
        _invalid("pid")
    for field, expected in (
        ("source_sha256", context["source_sha256"]),
        ("config_sha256", context["config_sha256"]),
        ("entrypoint_sha256", context["entrypoint_sha256"]),
    ):
        if response.get(field) != expected:
            _invalid(field)
    if response.get("bom") is not context["has_bom"]:
        _invalid("bom")
    if response.get("extract_key") != context["extract_key"]:
        _invalid("extract key")
    if response.get("split_sentinel") != context["sentinel"]:
        _invalid("split separator")
    literals = response.get("event_literal_pointers")
    if (
        not isinstance(literals, list)
        or any(not isinstance(item, str) for item in literals)
        or sorted(set(literals)) != sorted(context["event_literals"])
    ):
        _invalid("event literals")
    _validate_modules(response.get("modules"), context["upstream"])
    texts = response.get("texts")
    controls = response.get("controls")
    if not isinstance(texts, list) or not isinstance(controls, list):
        _invalid("text/control vector")
    if len(texts) != len(controls) or len(texts) > MAX_RECORDS:
        _invalid("text/control vector")
    for text in texts:
        if not isinstance(text, str) or text == "":
            _invalid("text value")
        try:
            if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
                _invalid("text size")
        except UnicodeEncodeError:
            _invalid("text encoding")
    for ctrl in controls:
        if not isinstance(ctrl, dict):
            _invalid("control value")
    if type(response.get("input_count")) is not int or response["input_count"] != 1:
        _invalid("input count")
    expected_output = 0 if operation == "extract" else 1
    if type(response.get("output_count")) is not int or response["output_count"] != expected_output:
        _invalid("output count")
    if response.get("is_input") is not (operation == "import"):
        _invalid("input flag")
    root = response.get("root")
    if not isinstance(root, str) or _norm(root) != _norm(main_dir):
        _invalid("phase root")
    manifest = _validate_manifest_schema(response.get("phase_manifest"), operation)
    return {
        "pid": pid,
        "texts": texts,
        "controls": controls,
        "manifest": manifest,
    }


def _parse_export(data):
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        _invalid("export json")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _invalid("export vector")
    return value


def _validate_records(records, document):
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        _invalid("records")
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "text",
            "locator",
            "candidate_pointers",
        }:
            _invalid("record row")
        text = record["text"]
        locator = record["locator"]
        pointers = record["candidate_pointers"]
        if not isinstance(text, str) or text == "":
            _invalid("record text")
        if not isinstance(locator, dict) or set(locator) != {
            "node_path",
            "span",
            "header_len",
            "whole_string",
            "ctrl",
        }:
            _invalid("record locator")
        if not isinstance(locator["ctrl"], dict):
            _invalid("record ctrl")
        if not isinstance(pointers, list) or any(
            not isinstance(pointer, str) for pointer in pointers
        ):
            _invalid("record pointers")
        node_path, start, end, whole, pointer = _backend_worker._sextractor_location(
            document, locator["ctrl"], text
        )
        if locator["header_len"] != HEADER_LEN:
            _invalid("record header")
        if locator["whole_string"] is not whole:
            _invalid("record proof")
        if locator["node_path"] != node_path or locator["span"] != [start, end]:
            _invalid("record position")
        expected_pointers = [pointer] if whole else []
        if pointers != expected_pointers:
            _invalid("record pointer")
    return records


def _scan_phase_files(main_dir, operation):
    main_dir = Path(main_dir)
    if not main_dir.is_absolute() or not main_dir.is_dir():
        _invalid("phase main directory")
    main_info = os.lstat(main_dir)
    if _is_reparse(main_info) or not stat.S_ISDIR(main_info.st_mode):
        _side_effect("main directory")
    found = {}
    for current, dirnames, filenames in os.walk(main_dir, followlinks=False):
        current_path = Path(current)
        for name in dirnames:
            path = current_path / name
            if path.relative_to(main_dir).as_posix() not in {"src", "document", "document/ctrl", "document/new"}:
                _side_effect("unlisted directory")
            try:
                info = os.lstat(path)
            except OSError:
                _side_effect("directory stat")
            if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                _side_effect("directory entry")
        for name in filenames:
            path = current_path / name
            try:
                info = os.lstat(path)
            except OSError:
                _side_effect("file stat")
            if _is_reparse(info) or not stat.S_ISREG(info.st_mode):
                _side_effect("file entry")
            if getattr(info, "st_nlink", 1) > 1:
                _side_effect("hardlink")
            if info.st_size > MAX_IO_BYTES:
                _side_effect("file size")
            rel = path.relative_to(main_dir).as_posix()
            found[rel] = path
    expected = ALLOWED_FILES[operation]
    extra = set(found) - expected
    missing = expected - set(found)
    if extra:
        _side_effect("unlisted file")
    if missing:
        _invalid("missing output")
    return found


def _verify_phase_disk(phase_dir, operation, context, response_manifest, seeds):
    main_dir = Path(phase_dir) / "main"
    found = _scan_phase_files(main_dir, operation)
    files = {}
    for rel in sorted(found):
        files[rel] = _read_bounded(
            found[rel], MAX_IO_BYTES, "BACKEND_SIDE_EFFECT", rel
        )
    manifest = []
    for rel in sorted(files):
        manifest.append(
            {"path": rel, "size": len(files[rel]), "sha256": _sha256(files[rel])}
        )
    computed = {row["path"]: row for row in manifest}
    if set(computed) != set(response_manifest):
        _invalid("manifest set")
    for path, row in computed.items():
        reported = response_manifest[path]
        if reported["size"] != row["size"] or reported["sha256"] != row["sha256"]:
            _invalid("manifest hash")
    expected_seeds = {
        "src/engine.ini": context["config_bytes"],
        "document/input.json": context["source_bytes"],
    }
    expected_seeds.update(seeds)
    for rel, expected in expected_seeds.items():
        if files[rel] != expected:
            _side_effect(f"changed seed {rel}")
    return {"files": files, "manifest": manifest}


def _validate_extract_response(response, context, phase_dir):
    main_dir = Path(phase_dir) / "main"
    common = _validate_common_phase(response, "extract", context, main_dir)
    records = _validate_records(response.get("records"), context["document"])
    texts = common["texts"]
    if [record["text"] for record in records] != texts:
        _invalid("record text vector")
    if [record["locator"]["ctrl"] for record in records] != common["controls"]:
        _invalid("record control vector")
    export = _decode_b64(
        response.get("export_base64"), "export_base64", MAX_REQUEST_BYTES
    )
    if _sha256(export) != response.get("export_sha256"):
        _invalid("export hash")
    if _parse_export(export) != texts:
        _invalid("export vector")
    translations = list(texts)
    used = set()
    for index, change in enumerate(context["requested"]):
        record = _unique_record(records, change, index)
        position = next(
            (position for position, current in enumerate(records) if current is record),
            None,
        )
        if position is None or position in used:
            _invalid("requested locator")
        used.add(position)
        translations[position] = change.text
    disk = _verify_phase_disk(phase_dir, "extract", context, common["manifest"], {})
    if disk["files"]["document/ctrl/all.orig.json"] != export:
        _invalid("export file")
    return {
        "texts": texts,
        "controls": common["controls"],
        "records": records,
        "translations": translations,
        "export": export,
        "export_sha256": _sha256(export),
        "pid": common["pid"],
        "root": str(main_dir),
        "manifest": disk["manifest"],
    }


def _validate_import_response(response, context, extract, phase_dir):
    main_dir = Path(phase_dir) / "main"
    common = _validate_common_phase(response, "import", context, main_dir)
    if common["texts"] != extract["texts"]:
        _invalid("text vector")
    if common["controls"] != extract["controls"]:
        _invalid("control vector")
    if response.get("export_sha256") != extract["export_sha256"]:
        _invalid("export hash")
    output = _decode_b64(
        response.get("output_base64"), "output_base64", MAX_OUTPUT_BYTES
    )
    if _sha256(output) != response.get("output_sha256"):
        _invalid("output hash")
    if output.startswith(BOM_UTF8) is not context["has_bom"]:
        _invalid("output bom")
    _assert_expected(output, context["expected"])
    seeds = {
        "document/ctrl/all.orig.json": extract["export"],
        "document/ctrl/all.trans.json": encode_translations(extract["translations"]),
    }
    disk = _verify_phase_disk(phase_dir, "import", context, common["manifest"], seeds)
    actual = disk["files"]["document/new/input.json"]
    if actual != output:
        _invalid("output file")
    if _parse_export(disk["files"]["document/ctrl/all.orig.json"]) != extract["texts"]:
        _invalid("import export vector")
    return {
        "output": actual,
        "output_sha256": _sha256(actual),
        "pid": common["pid"],
        "root": str(main_dir),
        "manifest": disk["manifest"],
    }


# ---------------------------------------------------------------------------
# public SExtractor entry (called by CompatibilityBridge.rewrite_document)
# ---------------------------------------------------------------------------
def rewrite_document(relative_path, payload, changes, work_root, backend_root):
    """Run the real extract + import phases and return the actual output bytes."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("BACKEND_PATH_INVALID")
    if not isinstance(backend_root, (str, os.PathLike)):
        raise ValueError("BACKEND_ROOT_INVALID")
    try:
        source = bytes(payload)
    except (TypeError, ValueError):
        raise ValueError("BACKEND_SOURCE_INVALID") from None
    source_bytes, document, has_bom, _decoded = _decode_source(source)
    root = Path(os.path.abspath(os.fspath(backend_root)))
    if not root.is_dir():
        raise ValueError("BACKEND_ROOT_INVALID")
    plan = build_plan(document, changes)
    upstream = _snapshot_upstream(root)
    wire_changes = _wire_changes(plan["requested"])
    context = {
        "source_bytes": source_bytes,
        "document": document,
        "expected": plan["expected"],
        "has_bom": has_bom,
        "requested": plan["requested"],
        "extract_key": plan["extract_key"],
        "event_literals": plan["event_literals"],
        "sentinel": plan["sentinel"],
        "source_sha256": _sha256(source_bytes),
        "config_bytes": upstream["config"],
        "config_sha256": upstream["config_sha256"],
        "entrypoint_sha256": upstream["entrypoint_sha256"],
        "upstream": upstream,
    }
    base_request = {
        "backend": "sextractor",
        "backend_root": str(root),
        "relative_path": relative_path,
        "source_base64": _b64(source_bytes),
        "source_sha256": context["source_sha256"],
        "config_base64": _b64(upstream["config"]),
        "config_sha256": context["config_sha256"],
        "bom": has_bom,
        "changes": wire_changes,
        "upstream_files": upstream["files"],
        "entrypoint_sha256": context["entrypoint_sha256"],
    }
    work = _compatibility._validate_work_root(work_root)
    case_dir = _compatibility._create_case_dir(work)
    try:
        (case_dir / "cwd").mkdir()
    except OSError:
        raise ValueError("BACKEND_WORK_ROOT_INVALID: case cwd") from None
    extract_response = _run_phase(
        case_dir, case_dir / "extract", "sextractor_main_extract", base_request
    )
    extract = _validate_extract_response(
        extract_response, context, case_dir / "extract"
    )
    translations_bytes = encode_translations(extract["translations"])
    import_request = dict(base_request)
    import_request.update(
        {
            "export_base64": _b64(extract["export"]),
            "export_sha256": extract["export_sha256"],
            "translations": extract["translations"],
            "translations_sha256": _sha256(translations_bytes),
        }
    )
    import_response = _run_phase(
        case_dir, case_dir / "import", "sextractor_main_import", import_request
    )
    imported = _validate_import_response(
        import_response, context, extract, case_dir / "import"
    )
    if imported["pid"] == extract["pid"]:
        _invalid("pid reuse")
    _require_upstream_unchanged(upstream)
    output = imported["output"]
    locators = []
    for index, change in enumerate(context["requested"]):
        record = _unique_record(extract["records"], change, index)
        rules = ["linked-choice-402", "mz-plugin-357", "approved-field-keys"]
        if change.pointer in context["event_literals"]:
            rules.append("approved-event-literal-122")
        locators.append(
            {
                "pointer": change.pointer,
                "ctrl": copy.deepcopy(record["locator"]["ctrl"]),
                "adapter_rules": rules,
            }
        )
    sidecar = {
        "backend": "sextractor",
        "relative_path": relative_path,
        "source_sha256": context["source_sha256"],
        "bom": has_bom,
        "requested_pointers": [change.pointer for change in context["requested"]],
        "locators": locators,
        "pipeline": {
            "entrypoint": ENTRYPOINT,
            "config_sha256": context["config_sha256"],
            "upstream_output_sha256": imported["output_sha256"],
            "phases": [
                {
                    "operation": "extract",
                    "pid": extract["pid"],
                    "root": extract["root"],
                    "entrypoint_sha256": context["entrypoint_sha256"],
                    "manifest": extract["manifest"],
                },
                {
                    "operation": "import",
                    "pid": imported["pid"],
                    "root": imported["root"],
                    "entrypoint_sha256": context["entrypoint_sha256"],
                    "manifest": imported["manifest"],
                },
            ],
        },
    }
    sidecar_path = case_dir / "sidecar.json"
    atomic_write(
        sidecar_path,
        json.dumps(sidecar, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    return {
        "output_bytes": output,
        "sidecar": sidecar,
        "sidecar_path": str(sidecar_path),
        "capabilities": dict(CAPABILITIES),
    }
