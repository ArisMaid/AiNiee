"""Standalone compatibility extraction, memory-write and main-entry phase worker.

This module is executed as a subprocess (it is never imported by the GUI). It
reads exactly one JSON request from stdin and writes exactly one JSON response
to stdout:

    request  = {"backend", "backend_root", "relative_path", "source"}
    response = {"ok": true, "backend", "records", "capabilities"}

Every small record has the shape ``{"text", "locator", "candidate_pointers"}``.
Large repeated arrays use a lossless shared pointer pool; consumers use
ExtractionPointerPool.pointer_lists rather than expanding each reference.
``candidate_pointers`` lists a pointer only when the upstream extractor proves
that the pointer resolves to the whole extracted string. Broad extractions stay
candidates: an empty list means "no writable pointer", and a duplicated text
yields every matching leaf pointer instead of an invented unique one.

Everything the third-party extractors print to stdout is captured with
``contextlib.redirect_stdout`` into a ``StringIO`` so the protocol channel stays
clean. Exceptions become ``{"ok": false, "error": ...}`` without dumping source
content.

Extraction boundaries (see docs/rpg/COMPAT_CONTRACT.md):
* stdlib only, no CLI applications, no GUI, no archives, no auto plugin loading;
* the read-only extraction path never calls ReadGame/InjectGame/mainExtract or
  any write routine of the vendored extractors; the explicit
  ``sextractor_main_extract`` / ``sextractor_main_import`` operations delegate
  to the isolated :mod:`SExtractorMainWorker` main-entry phases instead;
* read-only extraction creates, modifies or removes no project or game file;
* all extraction capabilities report ``write=False`` and ``extraction_only=True``.

The explicit ``operation=write`` protocol delegates only to BackendWriters'
in-memory APIs and returns bytes plus a sidecar. Parent services validate those
bytes before writing a private candidate or a new build staging file. Neither
operation is passed an original game directory.
"""

from __future__ import annotations

import contextlib
import base64
import copy
import importlib
import importlib.util
import io
import json
import os
import re
import sys
from types import SimpleNamespace

MAX_IO_BYTES = 16 * 1024 * 1024
ZERO_WIDTH = "\u200B"
RPGMTL_CHILDREN_FILE_ID = "::"
SEXTRACTOR_HEADER_LEN = 9
SEXTRACTOR_REG_DIC = {"search": r"^<[^>]+>([\s\S]+)$"}
SEXTRACTOR_EXTRACT_KEY = "name,description,nickname,profile"

_INDEX_PATTERN = re.compile(r"^[0-9]+$")
_UNRESOLVED = object()

_CAPABILITY_BASE = {
    "write": False,
    "extraction_only": True,
    "memory_only": True,
    "approved_display_text": False,
    "third_party_writes": False,
}


class _WorkerError(Exception):
    """Raised for every rejected request or failed upstream call."""


# ---------------------------------------------------------------------------
# protocol helpers
# ---------------------------------------------------------------------------
def _capabilities(**extra):
    capabilities = dict(_CAPABILITY_BASE)
    capabilities.update(extra)
    return capabilities


def _clean_detail(detail, limit=300):
    detail = " ".join(str(detail).split())
    if len(detail) > limit:
        detail = detail[:limit] + "..."
    return detail


def _safe_error_message(exc):
    if isinstance(exc, _WorkerError):
        return _clean_detail(exc)
    name = type(exc).__name__
    if isinstance(exc, json.JSONDecodeError):
        detail = f"{exc.msg} at line {exc.lineno} column {exc.colno}"
    else:
        detail = str(exc)
    detail = _clean_detail(detail)
    return f"{name}: {detail}" if detail else name


def _read_request(stream=None):
    from ModuleFolders.Infrastructure.Platform.WorkerProtocol import REQUEST_LIMIT,parse
    if stream is None:
        from ModuleFolders.Infrastructure.Platform.ProtocolInput import ProtocolInput
        stream=ProtocolInput(getattr(sys.stdin,'buffer',sys.stdin))
    raw=stream.readline(REQUEST_LIMIT+1)
    if isinstance(raw,str):raw=raw.encode('utf-8')
    if raw.strip()==b'{':
        rest=stream.read(REQUEST_LIMIT-len(raw)+1)
        raw+=rest.encode('utf-8') if isinstance(rest,str) else rest
    if len(raw) > REQUEST_LIMIT:
        raise _WorkerError(f"request exceeds the {MAX_IO_BYTES} byte bound")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _WorkerError("request is not valid UTF-8") from exc
    try:
        request = parse(raw,REQUEST_LIMIT)
    except (json.JSONDecodeError,ValueError) as exc:
        raise _WorkerError(
            "request is not valid JSON"
        ) from exc
    if not isinstance(request, dict):
        raise _WorkerError("request must be a JSON object")
    if 'protocol_version' not in request and len(raw)>MAX_IO_BYTES:raise _WorkerError('request exceeds byte bound')
    return request


def _write_result(result):
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(payload) > MAX_IO_BYTES:
        payload = json.dumps(
            {"ok": False, "error": f"response exceeds the {MAX_IO_BYTES} byte bound"},
            ensure_ascii=False,
        ).encode("utf-8")
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(payload.decode("utf-8"))
        sys.stdout.flush()
    else:
        stream.write(payload)
        stream.flush()


def _process(request):
    backend = request.get("backend")
    if backend not in _BACKENDS:
        raise _WorkerError(
            "unknown backend "
            f"{backend!r}; expected one of {', '.join(sorted(_BACKENDS))}"
        )
    backend_root = request.get("backend_root")
    if not isinstance(backend_root, str) or not backend_root:
        raise _WorkerError("backend_root must be a non-empty absolute path")
    if not os.path.isabs(backend_root):
        raise _WorkerError("backend_root must be an absolute path")
    backend_root = os.path.abspath(backend_root)
    if not os.path.isdir(backend_root):
        raise _WorkerError(f"backend_root is not an existing directory: {backend_root}")
    operation=request.get('operation','extract')
    if operation=='stev_project':
        if backend!='stev':raise _WorkerError('UNKNOWN_OPERATION')
        from ModuleFolders.Infrastructure.GameAdapters.StevProjectWorker import ProjectError,process_project
        try:return process_project(request)
        except ProjectError as error:raise _WorkerError(str(error)) from None
    relative_path = _validate_relative_path(request.get("relative_path"),formats=('.js',) if operation=='write_js' else ('.json',))
    if operation in ('write','write_js'):
        if operation=='write_js':
            from ModuleFolders.Infrastructure.GameAdapters.BackendJsWriter import write_js_document as write_document
        else:
            from ModuleFolders.Infrastructure.GameAdapters.BackendWriters import write_document
        encoded=request.get('source_base64')
        if not isinstance(encoded,str):raise _WorkerError('INVALID_SOURCE_BASE64')
        try:raw=base64.b64decode(encoded,validate=True)
        except ValueError as error:raise _WorkerError('INVALID_SOURCE_BASE64') from error
        result=write_document(backend,backend_root,relative_path,raw,request.get('changes'))
        output=result.pop('output_bytes')
        result.update(ok=True,backend=backend,output_base64=base64.b64encode(output).decode('ascii'))
        return result
    if operation in ('sextractor_main_extract','sextractor_main_import'):
        if backend!='sextractor':raise _WorkerError('UNKNOWN_OPERATION')
        from ModuleFolders.Infrastructure.GameAdapters.SExtractorMainWorker import PhaseError,process_phase
        try:return process_phase(request)
        except PhaseError as error:raise _WorkerError(str(error)) from None
    if request.get('operation','extract')!='extract':raise _WorkerError('UNKNOWN_OPERATION')
    source = request.get("source")
    if not isinstance(source, str):
        raise _WorkerError(
            "source must be a string containing the JSON document text"
        )
    if len(source) > MAX_IO_BYTES or len(source.encode("utf-8")) > MAX_IO_BYTES:
        raise _WorkerError(f"source exceeds the {MAX_IO_BYTES} byte bound")
    try:
        document = json.loads(source)
    except json.JSONDecodeError as exc:
        raise _WorkerError(
            f"source is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    records, capabilities = _BACKENDS[backend](
        backend_root, relative_path, document, source
    )
    from ModuleFolders.Infrastructure.GameAdapters.ExtractionPointerPool import pack_records
    return {
        "ok": True,
        "backend": backend,
        **pack_records(records),
        "capabilities": capabilities,
    }


# ---------------------------------------------------------------------------
# input validation / pointer helpers
# ---------------------------------------------------------------------------
def _validate_relative_path(relative_path,*,formats=('.json',)):
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise _WorkerError("relative_path must be a non-empty string")
    normalized = relative_path.strip().replace("\\", "/")
    if any(ord(character) < 32 for character in normalized):
        raise _WorkerError("relative_path must not contain control characters")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise _WorkerError("relative_path must be relative to the upstream data root")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise _WorkerError("relative_path must not escape the upstream data root")
    if not parts[-1].lower().endswith(formats):
        raise _WorkerError("BACKEND_PATH_INVALID: unsupported document extension")
    return "/".join(parts)


def _escape_pointer_segment(segment):
    return (
        str(segment)
        .replace("~", "~0")
        .replace("/", "~1")
    )


def _resolve_pointer(document, pointer):
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        return _UNRESOLVED
    node = document
    for raw in pointer.split("/")[1:]:
        segment = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            if not _INDEX_PATTERN.match(segment):
                return _UNRESOLVED
            index = int(segment)
            if index >= len(node):
                return _UNRESOLVED
            node = node[index]
        elif isinstance(node, dict):
            if segment not in node:
                return _UNRESOLVED
            node = node[segment]
        else:
            return _UNRESOLVED
    return node


def _leaf_pointer_index(document):
    """Map every non-empty string leaf to all of its JSON pointers."""
    index = {}

    def walk(node, pointer):
        if isinstance(node, str):
            if node != "":
                index.setdefault(node, []).append(pointer)
        elif isinstance(node, list):
            for position, child in enumerate(node):
                walk(child, pointer + "/" + str(position))
        elif isinstance(node, dict):
            for key, child in node.items():
                walk(child, pointer + "/" + _escape_pointer_segment(key))

    walk(document, "")
    return index


# ---------------------------------------------------------------------------
# upstream loading (explicit trusted roots only)
# ---------------------------------------------------------------------------
def _load_module(module_path, module_name):
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError("no import spec could be created")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            # Execute the inspected Python bytes, never an untracked cache
            # whose timestamp/size may coincidentally match the pinned source.
            with open(module_path,'rb') as handle:source=handle.read(MAX_IO_BYTES+1)
            if len(source)>MAX_IO_BYTES:raise ImportError('upstream source limit')
            exec(compile(source,os.fspath(module_path),'exec'),module.__dict__)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
    except BaseException as exc:
        raise _WorkerError(
            f"failed to import upstream module {module_path}: {_safe_error_message(exc)}"
        ) from exc
    return module


def _import_upstream(module_name):
    try:
        return importlib.import_module(module_name)
    except BaseException as exc:
        raise _WorkerError(
            "failed to import upstream module "
            f"{module_name!r}: {_safe_error_message(exc)}"
        ) from exc


# ---------------------------------------------------------------------------
# Stev (jr_tpp) backend
# ---------------------------------------------------------------------------
def _split_merge_suffix(address):
    if ZERO_WIDTH not in address:
        return address, None
    clean, _, suffix = address.partition(ZERO_WIDTH)
    try:
        merge_count = int(suffix)
    except (TypeError, ValueError):
        merge_count = None
    return clean, merge_count


def _stev_pointer(document, address, basename, text):
    prefix = basename + "\\"
    if address == basename:
        segments = []
    elif address.startswith(prefix):
        segments = address[len(prefix):].split("\\")
    else:
        return None, False
    pointer = "".join("/" + _escape_pointer_segment(segment) for segment in segments)
    resolved = _resolve_pointer(document, pointer)
    if isinstance(resolved, str) and resolved == text:
        return pointer, True
    return pointer, False


def _extract_stev(backend_root, relative_path, document, source):
    jtpp_path = os.path.join(backend_root, "jtpp.py")
    if not os.path.isfile(jtpp_path):
        raise _WorkerError(
            f"stev backend root does not contain jtpp.py: {jtpp_path}"
        )
    module = _load_module(jtpp_path, "ainiee_compat_stev_jtpp")
    reader_class = getattr(module, "Jr_Tpp", None)
    if reader_class is None:
        raise _WorkerError(f"jtpp.py does not define Jr_Tpp: {jtpp_path}")
    basename = relative_path.rsplit("/", 1)[-1]
    with contextlib.redirect_stdout(io.StringIO()):
        reader = reader_class(
            {"ja": False, "ReadCode": [], "sumcode": [], "sptext": {}}
        )
        read_file = getattr(reader, "_Jr_Tpp__ReadFile", None)
        if read_file is None:
            raise _WorkerError(
                "Jr_Tpp has no _Jr_Tpp__ReadFile; the upstream layout changed"
            )
        rows = list(read_file(document, basename))
        pending_length = getattr(reader, "_Jr_Tpp__sumlen", 0)
        pending = getattr(reader, "_Jr_Tpp__tempdata", None)
        if pending_length and isinstance(pending, list) and len(pending) >= 5:
            pending_text = pending[0]
            if isinstance(pending_text, str) and pending_text != "":
                pending_address = pending[2] if isinstance(pending[2], str) else ""
                if ZERO_WIDTH not in pending_address:
                    pending_address = (
                        pending_address + ZERO_WIDTH + str(pending_length)
                    )
                rows.append(
                    [
                        pending_text,
                        pending[1],
                        pending_address,
                        pending[3],
                        pending[4],
                    ]
                )
    records = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        text = row[0]
        if not isinstance(text, str) or text == "":
            continue
        raw_address = row[2] if isinstance(row[2], str) else ""
        address, merge_count = _split_merge_suffix(raw_address)
        pointer, whole_string = _stev_pointer(document, address, basename, text)
        code = row[4] if isinstance(row[4], str) else None
        records.append(
            {
                "text": text,
                "locator": {
                    "address": address,
                    "basename": basename,
                    "code": code,
                    "merge_count": merge_count,
                    "whole_string": whole_string,
                },
                "candidate_pointers": [pointer] if whole_string else [],
            }
        )
    return records, _capabilities(
        game_directory_read=False,
        spreadsheet_exports=False,
        auto_plugins_loaded=False,
        upstream_stdout_captured=True,
    )


# ---------------------------------------------------------------------------
# RPGMTL backend
# ---------------------------------------------------------------------------
def _extract_rpgmtl(backend_root, relative_path, document, source):
    plugin_file = os.path.join(backend_root, "plugins", "json.py")
    if not os.path.isfile(plugin_file):
        raise _WorkerError(
            f"rpgmtl backend root does not contain plugins/json.py: {plugin_file}"
        )
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    module = _import_upstream("plugins.json")
    plugin_class = getattr(module, "JSON", None)
    if plugin_class is None:
        raise _WorkerError(f"plugins/json.py does not define JSON: {plugin_file}")
    leaf_index = _leaf_pointer_index(document)
    with contextlib.redirect_stdout(io.StringIO()):
        plugin = plugin_class()
        plugin.set_settings({"json_rpgm_multiline": False})
        plugin.owner = SimpleNamespace(CHILDREN_FILE_ID=RPGMTL_CHILDREN_FILE_ID)
        groups = plugin.read(relative_path, source.encode("utf-8"))
    records = []
    for group_index, group in enumerate(groups or []):
        if not isinstance(group, (list, tuple)) or not group:
            continue
        label = group[0] if isinstance(group[0], str) else ""
        if label.startswith(RPGMTL_CHILDREN_FILE_ID):
            # Common-event groups are virtual children of the document; report
            # the virtual group itself as a candidate without a writable pointer.
            records.append(
                {
                    "text": label,
                    "locator": {
                        "group_index": group_index,
                        "item_index": 0,
                        "label": label,
                        "virtual": True,
                    },
                    "candidate_pointers": [],
                }
            )
        for item_index in range(1, len(group)):
            text = group[item_index]
            if not isinstance(text, str) or text == "":
                continue
            records.append(
                {
                    "text": text,
                    "locator": {
                        "group_index": group_index,
                        "item_index": item_index,
                        "label": label,
                        "virtual": False,
                    },
                    # The index owns these immutable-for-this-invocation lists.
                    # Repeated text must not allocate a quadratic number of
                    # pointer references before the shared wire encoding runs.
                    "candidate_pointers": leaf_index.get(text, []),
                }
            )
    return records, _capabilities(
        game_directory_read=False,
        upstream_write_calls=False,
        auto_plugins_loaded=False,
        upstream_stdout_captured=True,
    )


# ---------------------------------------------------------------------------
# SExtractor backend
# ---------------------------------------------------------------------------
def _configure_sextractor_vars(ex_var):
    """Explicit safe defaults for the attributes this limited parse API reads."""
    ex_var.regDic = dict(SEXTRACTOR_REG_DIC)
    ex_var.extractKey = SEXTRACTOR_EXTRACT_KEY
    ex_var.structure = ""
    ex_var.decrypt = ""
    ex_var.nameList = []
    ex_var.serialSearch = True
    ex_var.pureText = False
    ex_var.keepBytes = ""
    ex_var.ignoreDecodeError = False
    ex_var.postSkip = None
    ex_var.checkJIS = None
    ex_var.preLen = 0
    ex_var.preLenOffset = None
    ex_var.preLenScale = 1
    ex_var.preLenAdd = 0
    ex_var.preLenStrict = True
    ex_var.startline = 0
    ex_var.skipIgnoreUnfinish = False
    ex_var.skipIgnoreCtrl = False
    ex_var.nameKeepCtrl = False
    ex_var.printSetting = [False, False, False, False, False]
    ex_var.workpath = ""
    ex_var.window = None
    ex_var.indent = 0


def _sextractor_location(document, ctrl, text):
    position = ctrl.get("pos") if isinstance(ctrl, dict) else None
    if not (isinstance(position, (list, tuple)) and len(position) >= 3):
        return None, None, None, False, None
    node_path = list(position[0]) if isinstance(position[0], (list, tuple)) else None
    try:
        start = int(position[1]) - SEXTRACTOR_HEADER_LEN
        end = int(position[2]) - SEXTRACTOR_HEADER_LEN
    except (TypeError, ValueError):
        return node_path, None, None, False, None
    if node_path is None:
        return None, start, end, False, None
    pointer = "".join(
        "/" + _escape_pointer_segment(segment) for segment in node_path
    )
    resolved = _resolve_pointer(document, pointer)
    whole_string = (
        isinstance(resolved, str)
        and resolved == text
        and start == 0
        and end == len(resolved)
    )
    return node_path, start, end, whole_string, pointer if whole_string else None


def _extract_sextractor(backend_root, relative_path, document, source):
    source_root = os.path.join(backend_root, "src")
    engine_file = os.path.join(source_root, "extract_RPGMV.py")
    if not os.path.isfile(engine_file):
        raise _WorkerError(
            "sextractor backend root does not contain src/extract_RPGMV.py: "
            f"{engine_file}"
        )
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    common = _import_upstream("common")
    engine = _import_upstream("extract_RPGMV")
    ex_var = getattr(common, "ExVar", None)
    if ex_var is None:
        raise _WorkerError(
            f"common.py does not expose ExVar: {os.path.join(source_root, 'common.py')}"
        )
    _configure_sextractor_vars(ex_var)
    parse_imp = getattr(engine, "parseImp", None)
    if parse_imp is None:
        raise _WorkerError(f"extract_RPGMV.py does not expose parseImp: {engine_file}")

    records = []
    upstream_ctrls = []

    def deal_once(text, ctrl):
        snapshot = copy.deepcopy(ctrl)
        node_path, start, end, whole_string, pointer = _sextractor_location(
            document, snapshot, text
        )
        records.append(
            {
                "text": text,
                "locator": {
                    "node_path": node_path,
                    "span": [start, end],
                    "header_len": SEXTRACTOR_HEADER_LEN,
                    "whole_string": whole_string,
                    "ctrl": snapshot,
                },
                "candidate_pointers": [pointer] if whole_string else [],
            }
        )
        return True

    with contextlib.redirect_stdout(io.StringIO()):
        parse_imp(document, upstream_ctrls, deal_once)
    return records, _capabilities(
        cli_applications=False,
        gui_launched=False,
        file_writes=False,
        upstream_stdout_captured=True,
        # Upstream appends the ctrl it owns only when dealOnce returns True.
        upstream_ctrl_verified=len(upstream_ctrls) == len(records),
    )


_BACKENDS = {
    "stev": _extract_stev,
    "rpgmtl": _extract_rpgmtl,
    "sextractor": _extract_sextractor,
}


def main():
    try:
        from ModuleFolders.Infrastructure.Platform.ProtocolInput import ProtocolInput
        reader=ProtocolInput(getattr(sys.stdin,'buffer',sys.stdin))
        request=_read_request(reader)
        if 'protocol_version' in request:
            from ModuleFolders.Infrastructure.Platform.PythonWorker import serve
            serve(request,_process,result_limit=MAX_IO_BYTES,error_formatter=_safe_error_message,reader=reader)
        result = _process(request)
    except BaseException as exc:  # protocol must always produce one JSON answer
        result = {"ok": False, "error": _safe_error_message(exc)}
    _write_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
