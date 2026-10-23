"""One real whole-work-copy Stev ``ReadGame`` -> ``InjectGame`` project run.

The parent clones every declared source file into ``case_root/input`` and starts
this worker with an empty ``case_root/cwd``.  The worker derives both roots from
``case_root`` only, runs the actual vendored ``Jr_Tpp`` directory entry points
under a phase-scoped audited Python guard, and never accepts or uses an original
game-root path.

Only two fixed success artifacts are written by this worker:

* ``case_root/program-data.json`` immediately after the audited read phase;
* ``case_root/project-report.json`` after every round has been independently
  inspected and every source/round/upstream hash has been rechecked.

Round data directories are pre-created before the guard, and the only files the
guard permits are the exact ``data/**/*.json`` documents the real injector
enumerates.  Unchanged documents still pass through the real directory writer;
they are never patched or repaired by local JSON handling.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import builtins
import codecs
import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

from . import StevProjectCodec as codec
from .BackendWriters import _canonical_json, _strict_loads, _third_party_boundary
from .SExtractorMainWorker import (
    _PhaseGuard,
    _is_reparse,
    _norm,
    _norm_target,
)

__all__ = ["ProjectError", "process_project"]

MAX_FILES = 100_000
MAX_TOTAL = 32 * 1024 ** 3
MAX_DATA_JSON = 16 * 1024 * 1024
MAX_REPORT = 128 * 1024 * 1024
MAX_UPSTREAM = 16 * 1024 * 1024
MAX_ROUNDS = codec.MAX_ROUNDS
BOM_UTF8 = codecs.BOM_UTF8
COLUMNS = codec.COLUMNS
_INDEX_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*)$")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_INVALID_WINDOWS = frozenset('<>:"|?*')
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{index}" for index in range(1, 10)]
    + [f"LPT{index}" for index in range(1, 10)]
)
_MISSING = object()
_JTTP_MODULE_NAME = "ainiee_stev_project_jtpp"


class ProjectError(ValueError):
    """Stable structural failure for the ``stev_project`` operation.

    Messages contain only the stable code and a small structural hint; upstream
    exception text, game text and filesystem paths are never included.
    """

    def __init__(self, code, detail=None):
        self.code = str(code)
        self.detail = None if detail is None else str(detail)
        super().__init__(self.code if self.detail is None else f"{self.code}: {self.detail}")


def _fail(code, detail=None):
    raise ProjectError(code, detail)


def _from_codec(error):
    raise ProjectError(error.code, error.detail) from None


# ---------------------------------------------------------------------------
# phase-scoped guard
# ---------------------------------------------------------------------------
class _ProjectGuard(_PhaseGuard):
    """Deny every write except the exact round files and pre-created dirs."""

    def __init__(self, allowed_targets=(), allowed_mkdir=()):
        super().__init__(allowed_targets)
        self._allowed_mkdir = frozenset(
            _norm_target(path) for path in allowed_mkdir
        )

    def _audit(self, event, args):
        if not self.active:
            return
        if event == "os.mkdir":
            path = args[0] if args else None
            try:
                target = _norm_target(path)
            except (OSError, TypeError, ValueError):
                target = None
            if target is not None and target in self._allowed_mkdir:
                try:info=os.lstat(target)
                except OSError:pass
                else:
                    if stat.S_ISDIR(info.st_mode) and not getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
                        return
        return super()._audit(event, args)


# ---------------------------------------------------------------------------
# request/path validation helpers
# ---------------------------------------------------------------------------
def _lstat(path):
    try:
        return os.lstat(path)
    except OSError:
        return None


def _assert_normal_dir(path, code, detail="directory"):
    info = _lstat(path)
    if (
        info is None
        or not stat.S_ISDIR(info.st_mode)
        or _is_reparse(info)
    ):
        _fail(code, detail)
    return info


def _assert_regular(path, code, detail="file"):
    info = _lstat(path)
    if (
        info is None
        or not stat.S_ISREG(info.st_mode)
        or _is_reparse(info)
        or getattr(info, "st_nlink", 1) != 1
    ):
        _fail(code, detail)
    return info


def _request_path(value, label):
    if not isinstance(value, (str, os.PathLike)):
        _fail("BACKEND_REQUEST_INVALID", label)
    try:
        text = os.fspath(value)
    except TypeError:
        _fail("BACKEND_REQUEST_INVALID", label)
    if isinstance(text, bytes) or text == "" or "\x00" in text:
        _fail("BACKEND_REQUEST_INVALID", label)
    if not os.path.isabs(text):
        _fail("BACKEND_ROOT_INVALID", label)
    return Path(os.path.abspath(text))


def _safe_manifest_relative(value):
    if not isinstance(value, str) or value == "":
        _fail("BACKEND_SOURCE_INVALID", "manifest path")
    if "\\" in value or value.startswith("/") or _DRIVE_PREFIX.match(value):
        _fail("BACKEND_SOURCE_INVALID", "manifest path")
    for part in value.split("/"):
        if part in ("", ".", ".."):
            _fail("BACKEND_SOURCE_INVALID", "manifest segment")
        if any(ord(character) < 32 for character in part):
            _fail("BACKEND_SOURCE_INVALID", "manifest character")
        if any(character in _INVALID_WINDOWS for character in part):
            _fail("BACKEND_SOURCE_INVALID", "manifest character")
        if part != part.rstrip(" ."):
            _fail("BACKEND_SOURCE_INVALID", "manifest trailing character")
        if part.split(".")[0].upper() in _RESERVED_NAMES:
            _fail("BACKEND_SOURCE_INVALID", "manifest device name")
    return value


def _scan_tree(root, code="BACKEND_SIDE_EFFECT"):
    """Return ``(files, dirs, total)`` while rejecting links and hardlinks."""
    root = Path(root)
    _assert_normal_dir(root, code, "root directory")
    files = {}
    directories = set()
    total = 0

    def on_error(error):
        raise error

    try:
        walker = os.walk(root, topdown=True, onerror=on_error, followlinks=False)
        for current, dirnames, filenames in walker:
            current_path = Path(current)
            for name in dirnames:
                path = current_path / name
                info = _lstat(path)
                if (
                    info is None
                    or not stat.S_ISDIR(info.st_mode)
                    or _is_reparse(info)
                ):
                    _fail(code, "directory identity")
                directories.add(path.relative_to(root).as_posix())
            for name in filenames:
                path = current_path / name
                info = _lstat(path)
                if (
                    info is None
                    or not stat.S_ISREG(info.st_mode)
                    or _is_reparse(info)
                    or getattr(info, "st_nlink", 1) != 1
                ):
                    _fail(code, "file identity")
                relative = path.relative_to(root).as_posix()
                files[relative] = path
                total += info.st_size
    except ProjectError:
        raise
    except OSError:
        _fail(code, "walk")
    return files, directories, total


def _read_bounded(path, limit, code, detail="file"):
    info = _assert_regular(path, code, detail)
    if info.st_size > limit:
        _fail(code, "size")
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError:
        _fail(code, detail)
    if len(data) > limit:
        _fail(code, "size")
    return data


def _verify_file_hash(path, size, sha256, code, detail="file"):
    info = _assert_regular(path, code, detail)
    if info.st_size != size:
        _fail(code, detail)
    digest = hashlib.sha256()
    counted = 0
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                counted += len(block)
                if counted > size:
                    _fail(code, "size")
                digest.update(block)
    except OSError:
        _fail(code, detail)
    if counted != size or digest.hexdigest() != sha256:
        _fail(code, detail)


def _write_exclusive(path, payload, code="BACKEND_SIDE_EFFECT"):
    if not isinstance(payload, bytes):
        _fail(code, "payload")
    if os.path.lexists(path):
        _fail(code, "exists")
    try:
        with open(path, "xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        _fail(code, "write")
    info = _lstat(path)
    if (
        info is None
        or not stat.S_ISREG(info.st_mode)
        or _is_reparse(info)
        or getattr(info, "st_nlink", 1) != 1
        or info.st_size != len(payload)
    ):
        _fail(code, "write identity")


# ---------------------------------------------------------------------------
# request validation
# ---------------------------------------------------------------------------
def _validate_upstream(request, backend_root):
    rows = request.get("upstream_files")
    if not isinstance(rows, list) or len(rows) != 2:
        _fail("BACKEND_REQUEST_INVALID", "upstream files")
    by_name = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"path", "size", "sha256"}:
            _fail("BACKEND_REQUEST_INVALID", "upstream row")
        name = row["path"]
        if not isinstance(name, str) or name not in ("jtpp.py", "config.yaml"):
            _fail("BACKEND_REQUEST_INVALID", "upstream path")
        if name in by_name:
            _fail("BACKEND_REQUEST_INVALID", "upstream duplicate")
        if type(row["size"]) is not int or not 0 <= row["size"] <= MAX_UPSTREAM:
            _fail("BACKEND_REQUEST_INVALID", "upstream size")
        if not isinstance(row["sha256"], str) or _HEX64.fullmatch(row["sha256"]) is None:
            _fail("BACKEND_REQUEST_INVALID", "upstream hash")
        by_name[name] = row
    if set(by_name) != {"jtpp.py", "config.yaml"}:
        _fail("BACKEND_REQUEST_INVALID", "upstream set")
    snapshot = {}
    hashes = {}
    for name in ("jtpp.py", "config.yaml"):
        path = backend_root / name
        if _lstat(path) is None:
            _fail("BACKEND_UPSTREAM_MISSING", name)
        data = _read_bounded(path, MAX_UPSTREAM, "BACKEND_UPSTREAM_MISSING", name)
        digest = hashlib.sha256(data).hexdigest()
        row = by_name[name]
        if len(data) != row["size"] or digest != row["sha256"]:
            _fail("BACKEND_SOURCE_CHANGED", "upstream snapshot")
        snapshot[name] = data
        hashes[name] = digest
    return {"rows": rows, "by_name": by_name, "snapshot": snapshot, "hashes": hashes}


def _validate_manifest(request, game_root):
    rows = request.get("source_manifest")
    if not isinstance(rows, list):
        _fail("BACKEND_REQUEST_INVALID", "source manifest")
    if len(rows) > MAX_FILES:
        _fail("BACKEND_SOURCE_TOO_LARGE", "file count")
    by_path = {}
    seen_casefold = set()
    total = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"path", "size", "sha256"}:
            _fail("BACKEND_SOURCE_INVALID", "manifest row")
        relative = _safe_manifest_relative(row["path"])
        folded = relative.casefold()
        if relative in by_path or folded in seen_casefold:
            _fail("BACKEND_SOURCE_INVALID", "manifest duplicate")
        seen_casefold.add(folded)
        if type(row["size"]) is not int or row["size"] < 0:
            _fail("BACKEND_SOURCE_INVALID", "manifest size")
        if not isinstance(row["sha256"], str) or _HEX64.fullmatch(row["sha256"]) is None:
            _fail("BACKEND_SOURCE_INVALID", "manifest hash")
        if (
            relative.startswith("data/")
            and relative.endswith(".json")
            and row["size"] > MAX_DATA_JSON
        ):
            _fail("BACKEND_SOURCE_TOO_LARGE", "data json")
        total += row["size"]
        if total > MAX_TOTAL:
            _fail("BACKEND_SOURCE_TOO_LARGE", "total size")
        by_path[relative] = row
    files, directories, actual_total = _scan_tree(
        game_root, "BACKEND_SOURCE_INVALID"
    )
    if len(files) > MAX_FILES or actual_total > MAX_TOTAL:
        _fail("BACKEND_SOURCE_TOO_LARGE", "source tree")
    if set(files) != set(by_path):
        _fail("BACKEND_SIDE_EFFECT", "source file set")
    for relative in sorted(by_path):
        row = by_path[relative]
        _verify_file_hash(
            files[relative],
            row["size"],
            row["sha256"],
            "BACKEND_SOURCE_CHANGED",
            "source hash",
        )
    documents = sorted(
        relative
        for relative in by_path
        if relative.startswith("data/") and relative.endswith(".json")
    )
    if not documents:
        _fail("BACKEND_DOCUMENT_UNSUPPORTED", "data documents")
    return {
        "rows": rows,
        "by_path": by_path,
        "files": files,
        "directories": directories,
        "documents": documents,
    }


def _validate_case_root(case_root):
    _assert_normal_dir(case_root, "BACKEND_ROOT_INVALID", "case root")
    try:
        names = set(os.listdir(case_root))
    except OSError:
        _fail("BACKEND_ROOT_INVALID", "case root")
    if names != {"input", "cwd"}:
        _fail("BACKEND_ROOT_INVALID", "case root contents")
    game_root = case_root / "input"
    cwd = case_root / "cwd"
    _assert_normal_dir(game_root, "BACKEND_ROOT_INVALID", "input")
    _assert_normal_dir(cwd, "BACKEND_ROOT_INVALID", "cwd")
    try:
        if os.listdir(cwd):
            _fail("BACKEND_ROOT_INVALID", "cwd contents")
    except OSError:
        _fail("BACKEND_ROOT_INVALID", "cwd")
    return game_root, cwd


def _validate_request(request):
    if not isinstance(request, dict):
        _fail("BACKEND_REQUEST_INVALID", "request")
    if request.get("backend") != "stev":
        _fail("BACKEND_REQUEST_INVALID", "backend")
    if request.get("operation") != "stev_project":
        _fail("BACKEND_REQUEST_INVALID", "operation")
    backend_root = _request_path(request.get("backend_root"), "backend_root")
    _assert_normal_dir(backend_root, "BACKEND_ROOT_INVALID", "backend_root")
    case_root = _request_path(request.get("case_root"), "case_root")
    game_root, cwd = _validate_case_root(case_root)
    upstream = _validate_upstream(request, backend_root)
    manifest = _validate_manifest(request, game_root)
    changes = request.get("changes")
    try:
        validated_changes = codec.validate_changes(changes)
    except codec.CodecError as error:
        _from_codec(error)
    allowed = set(manifest["documents"])
    for relative_path in changes:
        if relative_path not in allowed:
            _fail("BACKEND_CHANGES_INVALID", "document")
    for change in validated_changes:
        if change["relative_path"] not in allowed:
            _fail("BACKEND_CHANGES_INVALID", "document")
    return {
        "backend_root": backend_root,
        "case_root": case_root,
        "game_root": game_root,
        "cwd": cwd,
        "upstream": upstream,
        "manifest": manifest,
        "documents": manifest["documents"],
        "changes": changes,
    }


# ---------------------------------------------------------------------------
# open/cleanup compatibility patches
# ---------------------------------------------------------------------------
def _norm_encoding(value):
    if not isinstance(value, str):
        return None
    return value.replace("_", "-").lower()


def _replace_encoding(args, kwargs, new_encoding):
    args = list(args)
    if len(args) >= 2:
        args[1] = new_encoding
        return tuple(args), kwargs
    kwargs = dict(kwargs)
    kwargs["encoding"] = new_encoding
    return tuple(args), kwargs


def _make_open_wrapper(read_paths, write_paths, bom_write_paths):
    original_open = builtins.open
    reads = frozenset(_norm_target(path) for path in read_paths)
    bom_writes = frozenset(_norm_target(path) for path in bom_write_paths)

    def wrapper(file, mode="r", *args, **kwargs):
        try:
            target = _norm_target(file) if not isinstance(file, int) else None
        except (OSError, TypeError, ValueError):
            target = None
        if target is not None and isinstance(mode, str) and "b" not in mode:
            writes_mode = any(character in mode for character in "wax+")
            encoding = args[1] if len(args) >= 2 else kwargs.get("encoding")
            normalized = _norm_encoding(encoding)
            if writes_mode:
                if target in bom_writes and (
                    encoding is None or normalized in ("utf8", "utf-8")
                ):
                    args, kwargs = _replace_encoding(args, kwargs, "utf-8-sig")
            elif target in reads and normalized in ("utf8", "utf-8"):
                args, kwargs = _replace_encoding(args, kwargs, "utf-8-sig")
        return original_open(file, mode, *args, **kwargs)

    return wrapper


def _patch_module_open(module, wrapper):
    previous = module.__dict__.get("open", _MISSING)
    module.__dict__["open"] = wrapper

    def restore():
        if previous is _MISSING:
            module.__dict__.pop("open", None)
        else:
            module.__dict__["open"] = previous

    return restore


def _patch_cleanup(reader):
    name = "_Jr_Tpp__del_marked_list"
    had_attribute = name in reader.__dict__
    previous = reader.__dict__.get(name, _MISSING)

    def identity(data, scenario=False):
        return data

    setattr(reader, name, identity)

    def restore():
        if had_attribute:
            setattr(reader, name, previous)
        else:
            try:
                delattr(reader, name)
            except AttributeError:
                pass

    return restore


# ---------------------------------------------------------------------------
# real read phase
# ---------------------------------------------------------------------------
def _load_jtpp(path,source):
    expected = _norm(path)
    if _JTTP_MODULE_NAME in sys.modules:
        sys.modules.pop(_JTTP_MODULE_NAME, None)
    try:
        spec = importlib.util.spec_from_file_location(_JTTP_MODULE_NAME, str(path))
    except (OSError, ValueError):
        _fail("BACKEND_UPSTREAM_FAILURE", "jtpp spec")
    if spec is None or spec.loader is None:
        _fail("BACKEND_UPSTREAM_FAILURE", "jtpp spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_JTTP_MODULE_NAME] = module
    try:
        # The exact captured and hashed source is the execution authority.
        # dont_write_bytecode alone does not disable reading old .pyc files.
        exec(compile(source,str(path),'exec'),module.__dict__)
    except BaseException:
        sys.modules.pop(_JTTP_MODULE_NAME, None)
        raise
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or _norm(module_file) != expected:
        _fail("BACKEND_SOURCE_CHANGED", "module provenance")
    return module


def _extract_reader(validated):
    guard = _ProjectGuard(())
    reader = None
    config = None
    pandas_module = None
    jtpp_module = None
    error = None
    try:
        guard.install()
        with _third_party_boundary():
            import pandas as pandas_module
            import yaml as _yaml  # noqa: F401
            import chardet as _chardet  # noqa: F401
            import openpyxl as _openpyxl  # noqa: F401

            config = codec.effective_config(
                validated["upstream"]["snapshot"]["config.yaml"]
            )
            jtpp_module = _load_jtpp(validated["backend_root"] / "jtpp.py",
                validated["upstream"]["snapshot"]["jtpp.py"])
            reader_class = getattr(jtpp_module, "Jr_Tpp", None)
            if not callable(reader_class):
                _fail("BACKEND_UPSTREAM_FAILURE", "Jr_Tpp")
            reader = reader_class(copy.deepcopy(config))
            restore_open = _patch_module_open(
                jtpp_module,
                _make_open_wrapper(
                    [
                        validated["game_root"] / relative
                        for relative in validated["documents"]
                    ],
                    [],
                    [],
                ),
            )
            try:
                reader.ReadGame(str(validated["game_root"]))
                reader.LabelName(reader.NameWithout)
            finally:
                restore_open()
    except ProjectError as exc:
        error = exc
    except codec.CodecError as exc:
        error = exc
    except BaseException as exc:
        error = exc
    finally:
        guard.close()
    if guard.violation is not None:
        raise ProjectError("BACKEND_SIDE_EFFECT", guard.violation)
    if isinstance(error, ProjectError):
        raise error
    if isinstance(error, codec.CodecError):
        _from_codec(error)
    if isinstance(error, (ImportError, ModuleNotFoundError)):
        raise ProjectError(
            "BACKEND_DEPENDENCY_MISSING", type(error).__name__
        ) from None
    if error is not None:
        raise ProjectError(
            "BACKEND_UPSTREAM_FAILURE", type(error).__name__
        ) from None
    return reader, config, pandas_module, jtpp_module


def _verify_source(validated):
    manifest = validated["manifest"]
    files, directories, _total = _scan_tree(
        validated["game_root"], "BACKEND_SOURCE_CHANGED"
    )
    if set(files) != set(manifest["by_path"]) or directories != manifest["directories"]:
        _fail("BACKEND_SOURCE_CHANGED", "source tree")
    for relative, row in manifest["by_path"].items():
        _verify_file_hash(
            files[relative],
            row["size"],
            row["sha256"],
            "BACKEND_SOURCE_CHANGED",
            "source hash",
        )


def _verify_upstream(validated):
    upstream = validated["upstream"]
    for name in ("jtpp.py", "config.yaml"):
        data = _read_bounded(
            validated["backend_root"] / name,
            MAX_UPSTREAM,
            "BACKEND_UPSTREAM_MISSING",
            name,
        )
        if data != upstream["snapshot"][name]:
            _fail("BACKEND_SOURCE_CHANGED", "upstream")
        if hashlib.sha256(data).hexdigest() != upstream["hashes"][name]:
            _fail("BACKEND_SOURCE_CHANGED", "upstream")


def _load_baseline(validated):
    from .StevSourceJson import parse_source_json
    documents = {}
    source_bom = {}
    source_duplicates=[]
    manifest = validated["manifest"]["by_path"]
    for relative in validated["documents"]:
        path = validated["game_root"] / relative
        raw = _read_bounded(
            path, MAX_DATA_JSON, "BACKEND_SOURCE_JSON_INVALID", "data json"
        )
        if hashlib.sha256(raw).hexdigest() != manifest[relative]["sha256"]:
            _fail("BACKEND_SOURCE_CHANGED", "data hash")
        source_bom[relative] = raw.startswith(BOM_UTF8)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            _fail("BACKEND_SOURCE_JSON_INVALID", "data encoding")
        try:
            documents[relative],duplicates=parse_source_json(raw,writable=bool(validated['changes'].get(relative)))
            if duplicates:source_duplicates.append({'path':relative,'keys':duplicates})
        except (ValueError, RecursionError) as error:
            if str(error)=='BACKEND_DUPLICATE_SOURCE_UNSUPPORTED':_fail('BACKEND_DUPLICATE_SOURCE_UNSUPPORTED')
            _fail("BACKEND_SOURCE_JSON_INVALID", "data json")
    return documents, source_bom, source_duplicates


# ---------------------------------------------------------------------------
# ProgramData artifact
# ---------------------------------------------------------------------------
def _program_payload(rows):
    try:
        payload = json.dumps(
            {"schema_version": 1, "rows": rows},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("BACKEND_PIPELINE_INVALID", "program data")
    if len(payload) > MAX_REPORT:
        _fail("BACKEND_OUTPUT_TOO_LARGE", "program data")
    return payload


# ---------------------------------------------------------------------------
# round preparation/build/audit
# ---------------------------------------------------------------------------
def _round_local_dirs(documents):
    directories = {""}
    for relative in documents:
        for parent in PurePosixPath(relative).parents:
            if str(parent) == ".":
                break
            directories.add(parent.as_posix())
    return directories


def _prepare_round_dirs(output_root, documents):
    output_root = Path(output_root)
    if os.path.lexists(output_root):
        _fail("BACKEND_SIDE_EFFECT", "round exists")
    try:
        output_root.mkdir(parents=True)
        (output_root / "data").mkdir()
        for relative in documents:
            (output_root / relative).parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        _fail("BACKEND_SIDE_EFFECT", "round directory")
    expected_dirs = _round_local_dirs(documents)
    files, directories, _total = _scan_tree(output_root)
    if files or directories != (expected_dirs - {""}):
        _fail("BACKEND_SIDE_EFFECT", "round directory set")
    result = [output_root]
    for relative in sorted(expected_dirs - {""}):
        result.append(output_root / relative)
    return result, expected_dirs


def _build_frames(pandas_module, changes):
    grouped = {}
    for item in changes:
        grouped.setdefault(item["file"], []).append(
            [
                item["source_text"],
                item["text"],
                item["address"],
                item["labels"],
                item["code"],
            ]
        )
    frames = {}
    try:
        for table_key, rows in grouped.items():
            frame = pandas_module.DataFrame(rows, columns=list(COLUMNS))
            frame.index = list(frame["原文"])
            if len(set(frame.index)) != len(frame.index):
                _fail("BACKEND_CHANGES_INVALID", "duplicate original")
            frames[table_key] = frame
    except ProjectError:
        raise
    except Exception:
        _fail("BACKEND_PIPELINE_INVALID", "frames")
    return frames


def _walk_parent(document, tokens):
    node = document
    for token in tokens:
        if isinstance(node, dict):
            if token not in node:
                return None
            node = node[token]
        elif isinstance(node, list):
            if _INDEX_PATTERN.match(token) is None:
                return None
            index = int(token)
            if index >= len(node):
                return None
            node = node[index]
        else:
            return None
    return node


def _apply_expected(expected, changes):
    for item in changes:
        try:
            tokens = codec.pointer_tokens(item["pointer"])
        except codec.CodecError as error:
            _from_codec(error)
        if not tokens:
            _fail("BACKEND_LOCATOR_UNSUPPORTED", "root pointer")
        parent = _walk_parent(expected[item["relative_path"]], tokens[:-1])
        if parent is None:
            _fail("BACKEND_LOCATOR_UNSUPPORTED", "pointer parent")
        last = tokens[-1]
        if isinstance(parent, dict):
            if last not in parent:
                _fail("BACKEND_LOCATOR_UNSUPPORTED", "pointer leaf")
            leaf = parent[last]
        elif isinstance(parent, list):
            if _INDEX_PATTERN.match(last) is None:
                _fail("BACKEND_LOCATOR_UNSUPPORTED", "pointer index")
            index = int(last)
            if index >= len(parent):
                _fail("BACKEND_LOCATOR_UNSUPPORTED", "pointer index")
            leaf = parent[index]
        else:
            _fail("BACKEND_LOCATOR_UNSUPPORTED", "pointer leaf")
        if not isinstance(leaf, str) or leaf != item["source_text"]:
            _fail("BACKEND_SOURCE_TEXT_MISMATCH", "source text")
        if isinstance(parent, dict):
            parent[last] = item["text"]
        else:
            parent[int(last)] = item["text"]


def _run_inject(
    reader,
    module,
    input_root,
    output_root,
    documents,
    local_dirs,
    bom_documents,
):
    write_paths = [output_root / relative for relative in documents]
    read_paths = [input_root / relative for relative in documents]
    bom_paths = [output_root / relative for relative in bom_documents]
    allowed_dirs = [output_root]
    allowed_dirs.extend(output_root / relative for relative in local_dirs if relative)
    guard = _ProjectGuard(write_paths, allowed_dirs)
    restore_open = _patch_module_open(
        module,
        _make_open_wrapper(read_paths, write_paths, bom_paths),
    )
    restore_cleanup = _patch_cleanup(reader)
    error = None
    try:
        guard.install()
        with _third_party_boundary():
            reader.InjectGame(str(input_root), str(output_root))
    except ProjectError as exc:
        error = exc
    except BaseException as exc:
        error = exc
    finally:
        guard.close()
        restore_open()
        restore_cleanup()
    if guard.violation is not None:
        raise ProjectError("BACKEND_SIDE_EFFECT", guard.violation)
    if isinstance(error, ProjectError):
        raise error
    if error is not None:
        raise ProjectError(
            "BACKEND_UPSTREAM_FAILURE", type(error).__name__
        ) from None


def _canonical(value):
    try:
        return _canonical_json(value)
    except Exception:
        _fail("BACKEND_UNAPPROVED_DIFF", "document type")


def _audit_round(
    output_root,
    documents,
    local_dirs,
    expected,
    baseline_documents,
    source_bom,
    manifest,
):
    files, directories, _total = _scan_tree(output_root)
    actual = set(files)
    known = set(documents)
    if actual - known:
        _fail("BACKEND_SIDE_EFFECT", "unexpected output")
    if known - actual:
        _fail("BACKEND_UNAPPROVED_DIFF", "missing output")
    if directories != (set(local_dirs) - {""}):
        _fail("BACKEND_SIDE_EFFECT", "output directory set")
    records = []
    for relative in documents:
        path = files[relative]
        raw = _read_bounded(
            path, MAX_DATA_JSON, "BACKEND_OUTPUT_TOO_LARGE", "output json"
        )
        if raw.startswith(BOM_UTF8) != source_bom[relative]:
            _fail("BACKEND_UNAPPROVED_DIFF", "bom")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            _fail("BACKEND_UNAPPROVED_DIFF", "encoding")
        try:
            document = _strict_loads(text)
        except (ValueError, RecursionError):
            _fail("BACKEND_UNAPPROVED_DIFF", "json")
        if _canonical(document) != _canonical(expected[relative]):
            _fail("BACKEND_UNAPPROVED_DIFF", "document")
        digest = hashlib.sha256(raw).hexdigest()
        source_digest = manifest[relative]["sha256"]
        records.append(
            {
                "path": relative,
                "size": len(raw),
                "sha256": digest,
                "source_sha256": source_digest,
                "byte_changed": digest != source_digest,
                "semantic_changed": _canonical(document)
                != _canonical(baseline_documents[relative]),
            }
        )
    return records


# ---------------------------------------------------------------------------
# final audit and report
# ---------------------------------------------------------------------------
def _verify_program_data(program_meta):
    path = Path(program_meta["_path"])
    payload = _read_bounded(
        path, MAX_REPORT, "BACKEND_SOURCE_CHANGED", "program data"
    )
    if len(payload) != program_meta["size"]:
        _fail("BACKEND_SOURCE_CHANGED", "program data")
    if hashlib.sha256(payload).hexdigest() != program_meta["sha256"]:
        _fail("BACKEND_SOURCE_CHANGED", "program data")


def _verify_rounds(rounds, documents):
    for record in rounds:
        files, directories, _total = _scan_tree(record["_output_root"])
        if set(files) != set(documents):
            _fail("BACKEND_SIDE_EFFECT", "round file set")
        if directories != (set(record["_directories"]) - {""}):
            _fail("BACKEND_SIDE_EFFECT", "round directory set")
        recorded = {item["path"]: item for item in record["files"]}
        for relative in documents:
            item = recorded[relative]
            payload = _read_bounded(
                files[relative],
                MAX_DATA_JSON,
                "BACKEND_OUTPUT_TOO_LARGE",
                "round output",
            )
            if len(payload) != item["size"]:
                _fail("BACKEND_SIDE_EFFECT", "round output")
            if hashlib.sha256(payload).hexdigest() != item["sha256"]:
                _fail("BACKEND_SIDE_EFFECT", "round output")


def _verify_case_tree(validated, rounds, program_meta):
    expected_files = {
        "input/" + relative for relative in validated["manifest"]["by_path"]
    }
    expected_files.add("program-data.json")
    expected_dirs = {"input", "cwd", "rounds"}
    for relative in validated["manifest"]["directories"]:
        expected_dirs.add("input/" + relative)
    for record in rounds:
        root = record["root"]
        expected_dirs.add(root)
        for relative in record["_directories"]:
            if relative:
                expected_dirs.add(root + "/" + relative)
        for item in record["files"]:
            expected_files.add(root + "/" + item["path"])
    files, directories, _total = _scan_tree(validated["case_root"])
    if set(files) != expected_files:
        if set(files) - expected_files:
            _fail("BACKEND_SIDE_EFFECT", "case file set")
        _fail("BACKEND_SOURCE_CHANGED", "case file set")
    if directories != expected_dirs:
        if directories - expected_dirs:
            _fail("BACKEND_SIDE_EFFECT", "case directory set")
        _fail("BACKEND_SOURCE_CHANGED", "case directory set")
    if os.listdir(validated["cwd"]):
        _fail("BACKEND_SIDE_EFFECT", "cwd not empty")
    _verify_program_data(program_meta)


def _serialize_report(report):
    try:
        payload = json.dumps(
            report, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("BACKEND_PIPELINE_INVALID", "report")
    if len(payload) > MAX_REPORT:
        _fail("BACKEND_OUTPUT_TOO_LARGE", "report")
    return payload


def _build_report(validated, config, program_meta, rows, rounds,source_duplicates):
    report_rounds = []
    for record in rounds:
        report_rounds.append(
            {
                "root": record["root"],
                "input_root": record["input_root"],
                "changes": record["changes"],
                "files": record["files"],
            }
        )
    return {
        "schema_version": 1,
        "backend": "stev",
        "entrypoint": "Jr_Tpp.ReadGame -> Jr_Tpp.InjectGame",
        "pid": os.getpid(),
        "game_root": str(validated["game_root"]),
        "source_files": len(validated["manifest"]["rows"]),
        "jtpp_sha256": validated["upstream"]["hashes"]["jtpp.py"],
        "config_sha256": validated["upstream"]["hashes"]["config.yaml"],
        "effective_config": config,
        "patches": ["utf8-sig-io", "disabled-list-cleanup"],
        "program_data": {
            "path": "program-data.json",
            "size": program_meta["size"],
            "sha256": program_meta["sha256"],
            "rows": len(rows),
        },
        "rounds": report_rounds,
        "source_duplicates":source_duplicates,
        "source_preserved": True,
        "upstream_preserved": True,
    }


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def _process(request):
    validated = _validate_request(request)
    reader, config, pandas_module, jtpp_module = _extract_reader(validated)
    _verify_source(validated)
    _verify_upstream(validated)
    baseline_documents, source_bom, source_duplicates = _load_baseline(validated)

    rows = codec.program_rows(reader, validated["game_root"])
    program_payload = _program_payload(rows)
    program_path = validated["case_root"] / "program-data.json"
    _write_exclusive(program_path, program_payload)
    program_meta = {
        "_path": program_path,
        "size": len(program_payload),
        "sha256": hashlib.sha256(program_payload).hexdigest(),
    }

    try:
        plan = codec.plan_rounds(rows, validated["changes"])
    except codec.CodecError as error:
        _from_codec(error)

    expected = copy.deepcopy(baseline_documents)
    previous_root = validated["game_root"]
    rounds = []
    for index, round_changes in enumerate(plan):
        if index >= MAX_ROUNDS:
            _fail("BACKEND_CHANGES_INVALID", "round count")
        output_root = validated["case_root"] / "rounds" / f"{index:04d}"
        local_dir_paths, local_dirs = _prepare_round_dirs(
            output_root, validated["documents"]
        )
        _apply_expected(expected, round_changes)
        reader.ProgramData = _build_frames(pandas_module, round_changes)
        _run_inject(
            reader,
            jtpp_module,
            previous_root,
            output_root,
            validated["documents"],
            local_dirs,
            [
                relative
                for relative in validated["documents"]
                if source_bom[relative]
            ],
        )
        files = _audit_round(
            output_root,
            validated["documents"],
            local_dirs,
            expected,
            baseline_documents,
            source_bom,
            validated["manifest"]["by_path"],
        )
        rounds.append(
            {
                "root": f"rounds/{index:04d}",
                "input_root": str(previous_root),
                "changes": round_changes,
                "files": files,
                "_output_root": output_root,
                "_directories": local_dirs,
            }
        )
        previous_root = output_root

    _verify_source(validated)
    _verify_upstream(validated)
    _verify_rounds(rounds, validated["documents"])
    _verify_case_tree(validated, rounds, program_meta)

    report = _build_report(validated, config, program_meta, rows, rounds,source_duplicates)
    report_payload = _serialize_report(report)
    report_path = validated["case_root"] / "project-report.json"
    _write_exclusive(report_path, report_payload)
    return {
        "ok": True,
        "backend": "stev",
        "operation": "stev_project",
        "pid": os.getpid(),
        "report_path": "project-report.json",
        "report_sha256": hashlib.sha256(report_payload).hexdigest(),
    }


def process_project(request: dict) -> dict:
    """Run one complete real Stev project read/inject cycle.

    Raises :class:`ProjectError` (a ``ValueError``) with a stable code on every
    rejected request, upstream failure, side effect or output mismatch.  The
    success report is written only after the complete final audit.
    """
    sys.dont_write_bytecode = True
    try:
        return _process(request)
    except ProjectError:
        raise
    except codec.CodecError as error:
        raise ProjectError(error.code, error.detail) from None
    except (ImportError, ModuleNotFoundError) as error:
        raise ProjectError(
            "BACKEND_DEPENDENCY_MISSING", type(error).__name__
        ) from None
    except BaseException as error:
        raise ProjectError(
            "BACKEND_PIPELINE_INVALID", type(error).__name__
        ) from None
