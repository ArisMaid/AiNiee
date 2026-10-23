"""One isolated, real SExtractor ``main_extract`` phase.

The module is imported by the standalone :mod:`BackendWorker` subprocess only.
Each invocation owns a brand-new private ``main`` directory next to its empty
cwd, writes the original document bytes and the captured ``src/engine.ini``,
then runs the real upstream ``main_extract_json.mainExtractJson`` (which calls
``main_extract.mainExtract``) under a phase-only audited Python guard.

The guard rejects every filesystem write except the single declared upstream
output of the phase, plus deletion/move/rename/subprocess/network attempts.  It
is not an OS sandbox; it protects the trusted, fixed SDK from unexpected effects
and is inert before the call and after it returns.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import os
import re
import stat
import sys

from ModuleFolders.Infrastructure.GameAdapters import BackendWorker as _backend
from ModuleFolders.Infrastructure.GameAdapters.BackendWriters import (
    WriterError,
    _assert_expected,
    _assert_expected_value,
    _third_party_boundary,
)
from ModuleFolders.Infrastructure.GameAdapters.SExtractorMainBridge import (
    ALLOWED_FILES,
    BOM_UTF8,
    HEADER_LEN,
    MAX_CHANGES,
    MAX_IO_BYTES,
    MAX_OUTPUT_BYTES,
    MAX_RECORDS,
    MAX_SOURCE_BYTES,
    MODULE_FILES,
    SOURCE_FILES,
    build_plan,
    encode_translations,
    split_para_sentinel,
)
from ModuleFolders.Service.GameProject.PathGuard import safe_join

__all__ = ["PhaseError", "process_phase"]

_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_WRITE_CHARS = frozenset("wax+")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_DENY_EVENTS = frozenset(
    {
        "os.remove",
        "os.rmdir",
        "os.rename",
        "os.replace",
        "os.unlink",
        "os.link",
        "os.symlink",
        "os.mkdir",
        "os.chmod",
        "os.chown",
        "os.utime",
        "os.truncate",
        "os.ftruncate",
        "os.chdir",
        "os.system",
        "os.exec",
        "os.spawn",
        "os.posix_spawn",
        "os.fork",
        "os.forkpty",
        "os.startfile",
        "pty.spawn",
        "subprocess.Popen",
        "shutil.rmtree",
        "shutil.move",
        "shutil.copyfile",
        "shutil.copymode",
        "shutil.copystat",
    }
)
_DENY_PREFIXES = (
    "socket.",
    "http.client.",
    "urllib.",
    "ftplib.",
    "smtplib.",
    "poplib.",
    "imaplib.",
    "nntplib.",
    "telnetlib.",
    "webbrowser.",
    "ssl.",
)


class PhaseError(ValueError):
    """Stable, structural phase failure (never contains source text)."""

    def __init__(self, code, detail=None):
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


class _AuditReject(RuntimeError):
    """Internal marker raised by the phase guard before an effect happens."""


def _invalid(detail=""):
    raise PhaseError("BACKEND_PIPELINE_INVALID" + (f": {detail}" if detail else ""))


def _side_effect(detail=""):
    raise PhaseError("BACKEND_SIDE_EFFECT" + (f": {detail}" if detail else ""))


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _norm(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def _is_reparse(info):
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE_FLAG)


def _exception_name(error):
    name = getattr(error, "name", None)
    if isinstance(name, str) and name:
        return name
    return type(error).__name__


def _decode_b64(value, label, limit):
    if not isinstance(value, str):
        _invalid(label)
    if len(value) > (limit * 4) // 3 + 4096:
        _invalid(label)
    try:
        data = base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        _invalid(label)
    if len(data) > limit:
        _invalid(label)
    return data


def _read_bounded(path, limit, code, label="file"):
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError:
        raise PhaseError(code, label) from None
    if len(data) > limit:
        raise PhaseError(code, label)
    return data


def _parse_export(data):
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        _invalid("export json")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _invalid("export vector")
    return value


# ---------------------------------------------------------------------------
# phase-only audited Python guard
# ---------------------------------------------------------------------------
def _norm_target(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fsdecode(path))))


def _open_write_intent(mode, flags):
    # ``io.open`` reports the mode string, ``os.open`` reports numeric flags;
    # use whichever form the audit event supplies.
    mode_writes = isinstance(mode, str) and any(character in mode for character in _WRITE_CHARS)
    flags_write = type(flags) is int and bool(flags & _WRITE_FLAGS)
    return mode_writes or flags_write or not (isinstance(mode, str) or type(flags) is int)


class _PhaseGuard:
    """Deny every unlisted filesystem effect while the upstream call runs."""

    def __init__(self, allowed_targets):
        self._allowed = frozenset(_norm_target(path) for path in allowed_targets)
        self.active = False
        self.violation = None
        self._saved = {}

    def install(self):
        for name in (
            "write",
            "writev",
            "pwrite",
            "pwritev",
            "ftruncate",
            "fchmod",
            "fchown",
        ):
            original = getattr(os, name, None)
            if original is None:
                continue
            self._saved[name] = original
            setattr(os, name, self._fd_denier(name))
        fdopen = getattr(os, "fdopen", None)
        if fdopen is not None:
            self._saved["fdopen"] = fdopen
            setattr(os, "fdopen", self._guarded_fdopen)
        sys.addaudithook(self._audit)
        self.active = True

    def close(self):
        self.active = False
        for name, original in self._saved.items():
            setattr(os, name, original)
        self._saved.clear()

    def _fd_denier(self, event):
        def denied(*args, **kwargs):
            self._reject(event)

        return denied

    def _guarded_fdopen(self, fd, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if not isinstance(mode, str) or any(
            character in mode for character in _WRITE_CHARS
        ):
            self._reject("os.fdopen")
        return self._saved["fdopen"](fd, *args, **kwargs)

    def _audit(self, event, args):
        if not self.active:
            return
        # pandas/platform reads the local machine name during import; this
        # performs no connection or name lookup. Socket creation/IO stays denied.
        if event == "socket.gethostname":
            return
        if event == "open":
            path = args[0] if args else None
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else None
            if not _open_write_intent(mode, flags):
                return
            if type(path) is int:
                self._reject("open-fd")
            if not isinstance(path, (str, bytes, os.PathLike)):
                self._reject("open-path")
            try:
                target = _norm_target(path)
            except (OSError, ValueError, TypeError):
                self._reject("open-path")
            if target not in self._allowed:
                self._reject("open")
            return
        if event in _DENY_EVENTS or event.startswith(_DENY_PREFIXES):
            self._reject(event)

    def _reject(self, event):
        if self.violation is None:
            self.violation = str(event)
        raise _AuditReject(event)


# ---------------------------------------------------------------------------
# request validation
# ---------------------------------------------------------------------------
def _validate_upstream_snapshot(request, root, config):
    rows = request.get("upstream_files")
    if not isinstance(rows, list) or len(rows) != len(SOURCE_FILES):
        _invalid("upstream files")
    snapshot = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "size", "sha256"}:
            _invalid("upstream row")
        name = row["path"]
        if (
            not isinstance(name, str)
            or name not in SOURCE_FILES
            or name in snapshot
        ):
            _invalid("upstream path")
        if type(row["size"]) is not int or not 0 <= row["size"] <= MAX_IO_BYTES:
            _invalid("upstream size")
        if not isinstance(row["sha256"], str) or _HEX64.fullmatch(row["sha256"]) is None:
            _invalid("upstream hash")
        snapshot[name] = row
    if set(snapshot) != set(SOURCE_FILES):
        _invalid("upstream set")
    try:
        source_root = safe_join(root, "src", must_exist=True)
    except ValueError:
        raise PhaseError("BACKEND_UPSTREAM_MISSING", "src") from None
    if not source_root.is_dir():
        raise PhaseError("BACKEND_UPSTREAM_MISSING", "src")
    entrypoint = None
    for name in SOURCE_FILES:
        try:
            path = safe_join(source_root, name, must_exist=True)
        except ValueError:
            raise PhaseError("BACKEND_DEPENDENCY_MISSING", f"src/{name}") from None
        if not path.is_file():
            raise PhaseError("BACKEND_DEPENDENCY_MISSING", f"src/{name}")
        try:
            info = os.lstat(path)
        except OSError:
            raise PhaseError("BACKEND_DEPENDENCY_MISSING", f"src/{name}") from None
        if (
            _is_reparse(info)
            or not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_nlink", 1) > 1
        ):
            _invalid("source provenance")
        data = _read_bounded(path, MAX_IO_BYTES, "BACKEND_PIPELINE_INVALID", name)
        if len(data) != snapshot[name]["size"] or _sha256(data) != snapshot[name]["sha256"]:
            _invalid("source hash")
        if name == "engine.ini":
            if data != config:
                _invalid("config provenance")
        elif name == "main_extract.py":
            entrypoint = _sha256(data)
    if request.get("entrypoint_sha256") != entrypoint:
        _invalid("entrypoint")
    return {
        "src_root": source_root,
        "snapshot": snapshot,
        "entrypoint_sha256": entrypoint,
    }


def _validate_request(request, phase):
    if not isinstance(request, dict):
        _invalid("request")
    if request.get("backend") != "sextractor":
        _invalid("backend")
    relative_path = request.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path.strip():
        _invalid("relative path")
    root_text = request.get("backend_root")
    if not isinstance(root_text, str) or not os.path.isabs(root_text):
        _invalid("backend root")
    root = os.path.abspath(root_text)
    if not os.path.isdir(root):
        _invalid("backend root")
    source = _decode_b64(request.get("source_base64"), "source", MAX_SOURCE_BYTES)
    if _sha256(source) != request.get("source_sha256"):
        _invalid("source hash")
    from ModuleFolders.Infrastructure.GameAdapters.BackendWriters import _decode_source

    try:
        source_bytes, document, has_bom, _decoded = _decode_source(source)
    except WriterError as error:
        raise PhaseError(str(error)) from None
    if type(request.get("bom")) is not bool or request.get("bom") is not has_bom:
        _invalid("bom")
    config = _decode_b64(request.get("config_base64"), "config", MAX_IO_BYTES)
    if _sha256(config) != request.get("config_sha256"):
        _invalid("config hash")
    upstream = _validate_upstream_snapshot(request, root, config)
    changes = request.get("changes")
    if not isinstance(changes, list) or len(changes) > MAX_CHANGES:
        _invalid("changes")
    try:
        plan = build_plan(document, changes)
    except WriterError as error:
        raise PhaseError(str(error)) from None
    phase_root_text = request.get("phase_root")
    if not isinstance(phase_root_text, str) or not os.path.isabs(phase_root_text):
        _invalid("phase root")
    phase_root = os.path.abspath(phase_root_text)
    if not os.path.isdir(phase_root):
        _invalid("phase root")
    try:
        phase_info = os.lstat(phase_root)
    except OSError:
        _invalid("phase root")
    if _is_reparse(phase_info) or not stat.S_ISDIR(phase_info.st_mode):
        _invalid("phase root")
    expected_cwd = os.path.join(phase_root, "cwd")
    if _norm(os.getcwd()) != _norm(expected_cwd):
        _invalid("phase cwd")
    main_dir = os.path.join(phase_root, "main")
    if os.path.lexists(main_dir):
        _invalid("main directory")
    translations = None
    translations_bytes = None
    export_bytes = None
    if phase == "import":
        export_bytes = _decode_b64(
            request.get("export_base64"), "export", MAX_IO_BYTES
        )
        if _sha256(export_bytes) != request.get("export_sha256"):
            _invalid("export hash")
        _parse_export(export_bytes)
        translations = request.get("translations")
        if not isinstance(translations, list) or len(translations) > MAX_RECORDS:
            _invalid("translations")
        total = 0
        for value in translations:
            if not isinstance(value, str):
                _invalid("translation value")
            try:
                total += len(value.encode("utf-8"))
            except UnicodeEncodeError:
                _invalid("translation encoding")
            if total > MAX_OUTPUT_BYTES:
                _invalid("translations size")
        translations_bytes = encode_translations(translations)
        if _sha256(translations_bytes) != request.get("translations_sha256"):
            _invalid("translations hash")
        if split_para_sentinel(document, translations) != plan["sentinel"]:
            _invalid("split separator")
    seeds = {
        "src/engine.ini": config,
        "document/input.json": source_bytes,
    }
    if phase == "import":
        seeds["document/ctrl/all.orig.json"] = export_bytes
        seeds["document/ctrl/all.trans.json"] = translations_bytes
    if phase == "extract":
        allowed_output = os.path.join(
            main_dir, "document", "ctrl", "all.orig.json"
        )
    else:
        allowed_output = os.path.join(main_dir, "document", "new", "input.json")
    if not os.path.isabs(main_dir):
        _invalid("main directory")
    return {
        "phase": phase,
        "plan": plan,
        "document": document,
        "source_bytes": source_bytes,
        "has_bom": has_bom,
        "config": config,
        "upstream": upstream,
        "phase_root": phase_root,
        "main": main_dir,
        "seeds": seeds,
        "translations": translations,
        "translations_bytes": translations_bytes,
        "export_bytes": export_bytes,
        "allowed_output": allowed_output,
    }


# ---------------------------------------------------------------------------
# private working directory
# ---------------------------------------------------------------------------
def _prepare_main(main_dir, seeds):
    if os.path.lexists(main_dir):
        _invalid("main directory")
    try:
        os.mkdir(main_dir)
    except OSError:
        _invalid("main directory")
    info = os.lstat(main_dir)
    if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
        _side_effect("main directory")
    try:
        for relative in ("src", "document", "document/ctrl", "document/new"):
            try:
                path = safe_join(main_dir, relative)
            except ValueError:
                _invalid("working directory")
            try:
                os.mkdir(path)
            except OSError:
                _invalid("working directory")
        for relative, data in seeds.items():
            try:
                path = safe_join(main_dir, relative)
            except ValueError:
                _invalid("seed path")
            try:
                with open(path, "xb") as handle:
                    handle.write(data)
            except OSError:
                _invalid("seed write")
    except PhaseError:
        raise


def _build_args(document_dir, extract_key, sentinel, has_bom, phase):
    return {
        "workpath": document_dir,
        "engineName": "RPGMV",
        "file": "json",
        "outputFormat": 7,
        "outputFormatExtra": -1,
        "outputPartMode": 0,
        "nameList": "",
        "regDic": r"10_search=^<[^>]+>([\s\S]+)$",
        "splitParaSep": sentinel,
        "print": [False] * 5,
        "encode": "utf-8-sig,utf-8-sig" if has_bom else "utf-8,utf-8",
        "extractKey": extract_key,
        "structure": "",
        "transReplace": False,
        "preReplace": False,
        "noInput": phase == "extract",
        "splitAuto": False,
        "tunnelJis": False,
        "subsJis": False,
        "toFullWidth": False,
        "dontInterrupt": False,
        "cutoff": False,
        "cutoffCopy": False,
        "textAppend": False,
        "dontExportWhenImport": True,
        "ignoreEmptyFile": False,
        "padding": " ",
        "allowEmpty": True,
        "joinAfterSplit": False,
        "nameMoveUp": False,
        "decrypt": "",
        "dynamicReplace": None,
        "preLen": 0,
        "useStructPara": False,
        "mergePara": False,
        "outputTextType": False,
        "dontImportName": False,
        "cutoffByOrig": False,
        "serialSearch": True,
        "nameKeepCtrl": False,
        "ignoreDecodeError": False,
        "postSkip": None,
        "checkJIS": None,
        "keepBytes": "",
        "startline": 0,
        "extraData": "",
        "version": "0",
        "encrypt": True,
    }


# ---------------------------------------------------------------------------
# upstream imports and event-rule scoping
# ---------------------------------------------------------------------------
def _drop_foreign_modules(source_root):
    prefix = _norm(source_root) + os.sep
    for name in MODULE_FILES:
        module = sys.modules.get(name)
        if module is None:
            continue
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str) or not module_file:
            sys.modules.pop(name, None)
            continue
        if not _norm(module_file).startswith(prefix):
            sys.modules.pop(name, None)


def _import_runtime_dependencies():
    try:
        with _third_party_boundary():
            import pandas  # noqa: F401
            import rapidjson  # noqa: F401
            from PyQt5.QtCore import QSettings  # noqa: F401
    except (ImportError, ModuleNotFoundError) as error:
        raise PhaseError("BACKEND_DEPENDENCY_MISSING", _exception_name(error)) from None


def _import_upstream(source_root, snapshot):
    _drop_foreign_modules(source_root)
    source_text = os.fspath(source_root)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    try:
        with _third_party_boundary():
            import main_extract  # noqa: F401
            import main_extract_json  # noqa: F401
            import extract_RPGMV  # noqa: F401
            import main_extract_part  # noqa: F401
            import var_extract  # noqa: F401
            import common  # noqa: F401
            import helper_text  # noqa: F401
            import helper_read  # noqa: F401
            import helper_write  # noqa: F401
            import extract_TXT  # noqa: F401
    except (ImportError, ModuleNotFoundError) as error:
        raise PhaseError("BACKEND_DEPENDENCY_MISSING", _exception_name(error)) from None
    modules = {}
    for name in MODULE_FILES:
        module = sys.modules.get(name)
        if module is None:
            raise PhaseError("BACKEND_DEPENDENCY_MISSING", name)
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str) or not module_file:
            _invalid("module provenance")
        expected = os.path.join(source_text, MODULE_FILES[name])
        if _norm(module_file) != _norm(expected):
            _invalid("module provenance")
        if _sha256(_read_bounded(module_file, MAX_IO_BYTES, "BACKEND_PIPELINE_INVALID", name)) != snapshot[
            MODULE_FILES[name]
        ]["sha256"]:
            _invalid("module hash")
        modules[name] = module
    return modules


def _enable_event_codes(engine, event_literals):
    table = engine.EVENT_COMMAND_CODES
    previous = {code: copy.deepcopy(table.get(code)) for code in (402, 357, 122)}
    table[402] = ["Choice branch label", True, True]
    table[357] = ["MZ plugin command", True, True]
    if event_literals:
        table[122] = ["Approved event display literal", True, True]
    return previous


def _restore_event_codes(engine, previous):
    try:
        table = engine.EVENT_COMMAND_CODES
        for code, value in previous.items():
            if value is None:
                table.pop(code, None)
            else:
                table[code] = value
    except BaseException:
        # The process is discarded after this phase; restoring the table must
        # never mask the upstream failure that is being reported.
        return


# ---------------------------------------------------------------------------
# result inspection
# ---------------------------------------------------------------------------
def _build_records(document, texts, controls):
    records = []
    for text, ctrl in zip(texts, controls):
        snapshot = copy.deepcopy(ctrl)
        node_path, start, end, whole, pointer = _backend._sextractor_location(
            document, snapshot, text
        )
        records.append(
            {
                "text": text,
                "locator": {
                    "node_path": node_path,
                    "span": [start, end],
                    "header_len": HEADER_LEN,
                    "whole_string": whole,
                    "ctrl": snapshot,
                },
                "candidate_pointers": [pointer] if whole else [],
            }
        )
    return records


def _collect_main_files(main_dir, phase):
    main_path = os.path.abspath(main_dir)
    try:
        main_info = os.lstat(main_path)
    except OSError:
        _invalid("main directory")
    if _is_reparse(main_info) or not stat.S_ISDIR(main_info.st_mode):
        _side_effect("main directory")
    found = {}
    for current, dirnames, filenames in os.walk(main_path, followlinks=False):
        for name in dirnames:
            path = os.path.join(current, name)
            if os.path.relpath(path, main_path).replace("\\", "/") not in {"src", "document", "document/ctrl", "document/new"}:
                _side_effect("unlisted directory")
            try:
                info = os.lstat(path)
            except OSError:
                _side_effect("directory stat")
            if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                _side_effect("directory entry")
        for name in filenames:
            path = os.path.join(current, name)
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
            relative = os.path.relpath(path, main_path).replace("\\", "/")
            found[relative] = path
    expected = ALLOWED_FILES[phase]
    if set(found) - expected:
        _side_effect("unlisted file")
    if expected - set(found):
        _invalid("missing output")
    return found


def _verify_effects(main_dir, phase, seeds):
    found = _collect_main_files(main_dir, phase)
    files = {}
    for relative in sorted(found):
        files[relative] = _read_bounded(
            found[relative], MAX_IO_BYTES, "BACKEND_SIDE_EFFECT", relative
        )
    for relative, expected in seeds.items():
        if files[relative] != expected:
            _side_effect(f"changed seed {relative}")
    manifest = [
        {
            "path": relative,
            "size": len(files[relative]),
            "sha256": _sha256(files[relative]),
        }
        for relative in sorted(files)
    ]
    return files, manifest


def _module_metadata(modules, source_root, snapshot):
    rows = []
    for name in sorted(MODULE_FILES):
        path = os.path.join(os.fspath(source_root), MODULE_FILES[name])
        data = _read_bounded(path, MAX_IO_BYTES, "BACKEND_PIPELINE_INVALID", name)
        digest = _sha256(data)
        if digest != snapshot[MODULE_FILES[name]]["sha256"]:
            _invalid("module hash")
        rows.append(
            {"name": name, "path": MODULE_FILES[name], "sha256": digest}
        )
    return rows


# ---------------------------------------------------------------------------
# phase entry point
# ---------------------------------------------------------------------------
def process_phase(request):
    """Validate one phase request, run the real entry point and return evidence."""
    sys.dont_write_bytecode = True
    try:
        return _process(request)
    except PhaseError:
        raise
    except WriterError as error:
        raise PhaseError(str(error)) from None
    except (ImportError, ModuleNotFoundError) as error:
        raise PhaseError("BACKEND_DEPENDENCY_MISSING", _exception_name(error)) from None
    except BaseException as error:
        raise PhaseError("BACKEND_PIPELINE_INVALID", type(error).__name__) from None


def _process(request):
    operation = request.get("operation") if isinstance(request, dict) else None
    if operation not in ("sextractor_main_extract", "sextractor_main_import"):
        _invalid("operation")
    phase = "extract" if operation.endswith("extract") else "import"
    validated = _validate_request(request, phase)
    plan = validated["plan"]
    main_dir = validated["main"]
    _prepare_main(main_dir, validated["seeds"])
    args = _build_args(
        os.path.join(main_dir, "document"),
        plan["extract_key"],
        plan["sentinel"],
        validated["has_bom"],
        phase,
    )
    guard = _PhaseGuard([validated["allowed_output"]])
    original_cwd = os.getcwd()
    modules = None
    previous = None
    try:
        os.chdir(main_dir)
        guard.install()
        _import_runtime_dependencies()
        modules = _import_upstream(
            validated["upstream"]["src_root"], validated["upstream"]["snapshot"]
        )
        previous = _enable_event_codes(
            modules["extract_RPGMV"], plan["event_literals"]
        )
        try:
            with _third_party_boundary():
                modules["main_extract_json"].mainExtractJson(args)
        finally:
            _restore_event_codes(modules["extract_RPGMV"], previous)
    except PhaseError:
        if guard.violation is not None:
            raise PhaseError("BACKEND_SIDE_EFFECT", guard.violation) from None
        raise
    except WriterError as error:
        raise PhaseError(str(error)) from None
    except (ImportError, ModuleNotFoundError) as error:
        raise PhaseError("BACKEND_DEPENDENCY_MISSING", _exception_name(error)) from None
    except BaseException as error:
        if guard.violation is not None:
            raise PhaseError("BACKEND_SIDE_EFFECT", guard.violation) from None
        raise PhaseError("BACKEND_UPSTREAM_FAILURE", type(error).__name__) from None
    finally:
        guard.close()
        try:
            os.chdir(original_cwd)
        except OSError:
            pass

    if guard.violation is not None:
        # A denied effect must fail the phase even if upstream swallowed it.
        raise PhaseError("BACKEND_SIDE_EFFECT", guard.violation)

    ex_var = modules["common"].ExVar
    if type(ex_var.inputCount) is not int or ex_var.inputCount != 1:
        _invalid("input count")
    expected_outputs = 0 if phase == "extract" else 1
    if type(ex_var.outputCount) is not int or ex_var.outputCount != expected_outputs:
        _invalid("output count")
    if bool(ex_var.isInput) is not (phase == "import"):
        _invalid("input flag")
    texts = list(ex_var.listOrig)
    controls_raw = list(ex_var.listCtrl)
    if len(texts) != len(controls_raw):
        _invalid("control count")
    for text in texts:
        if not isinstance(text, str) or text == "":
            _invalid("text value")
    controls = [copy.deepcopy(control) for control in controls_raw]
    for control in controls:
        if not isinstance(control, dict):
            _invalid("control value")
    try:
        _assert_expected_value(
            ex_var.content, validated["document"] if phase == "extract" else plan["expected"]
        )
    except WriterError as error:
        raise PhaseError(str(error)) from None
    files, manifest = _verify_effects(main_dir, phase, validated["seeds"])
    actual_export = files["document/ctrl/all.orig.json"]
    exported = _parse_export(actual_export)
    if exported != texts:
        _invalid("export vector")
    output = None
    if phase == "import":
        if actual_export != validated["export_bytes"]:
            _side_effect("changed seed document/ctrl/all.orig.json")
        output = files["document/new/input.json"]
        if len(output) > MAX_OUTPUT_BYTES:
            raise PhaseError("BACKEND_OUTPUT_TOO_LARGE")
        if output.startswith(BOM_UTF8) is not validated["has_bom"]:
            _invalid("output bom")
        try:
            _assert_expected(output, plan["expected"])
        except WriterError as error:
            raise PhaseError(str(error)) from None
    modules_meta = _module_metadata(
        modules, validated["upstream"]["src_root"], validated["upstream"]["snapshot"]
    )
    entrypoint = validated["upstream"]["entrypoint_sha256"]
    response = {
        "ok": True,
        "backend": "sextractor",
        "operation": phase,
        "pid": os.getpid(),
        "root": main_dir,
        "source_sha256": _sha256(validated["source_bytes"]),
        "config_sha256": _sha256(validated["config"]),
        "bom": validated["has_bom"],
        "entrypoint_sha256": entrypoint,
        "modules": modules_meta,
        "extract_key": plan["extract_key"],
        "event_literal_pointers": sorted(plan["event_literals"]),
        "split_sentinel": plan["sentinel"],
        "texts": texts,
        "controls": controls,
        "input_count": 1,
        "output_count": expected_outputs,
        "is_input": phase == "import",
        "export_sha256": _sha256(actual_export),
        "export_base64": _b64(actual_export),
        "phase_manifest": manifest,
    }
    if phase == "extract":
        response["records"] = _build_records(
            validated["document"], texts, controls_raw
        )
    else:
        response["output_sha256"] = _sha256(output)
        response["output_base64"] = _b64(output)
    return response
