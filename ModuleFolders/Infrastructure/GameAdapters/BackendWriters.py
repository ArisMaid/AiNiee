"""Memory-only third-party write worker for the compatibility bridge.

:func:`write_document` is the only entry point.  It is meant to be called
INSIDE a fresh, dedicated worker process (never by the GUI process) and applies
one exact set of whole-leaf translations through the real in-memory write API
of one vendored extractor:

* ``stev``: ``Jr_Tpp._Jr_Tpp__WriteFile`` (returns the mutated document);
* ``sextractor``: ``extract_RPGMV.replaceOnceImp`` + ``replaceEndImp``;
* ``rpgmtl``: ``plugins.json.JSON.read``/``write`` with a pointer-carrying
  ``LocatedString`` traversal and a locally scoped ``json`` proxy.

Hard boundaries:

* no CLI application, importer, ``ReadGame``/``InjectGame``, ``mainExtract``,
  project ``Save``, patch/fix script or spreadsheet export is called, and no
  third-party routine that writes a directory or a file;
* no game directory is accepted or needed - the caller already owns the bytes;
* every third-party call runs inside a bounded, discarding stdout/stderr
  capture (stdin is emptied too, so an upstream ``input()`` cannot hang the
  worker) and no raw upstream log is ever returned;
* the document produced by the upstream API is compared against an expected
  document built exclusively from the requested whole-leaf assignments; any
  mismatch is ``BACKEND_UNAPPROVED_DIFF`` and is never repaired by a local
  writer.

The caller stays responsible for approved-display-field and TokenPolicy
validation.  Nothing here claims that arbitrary strings that come out of a
third-party extractor are approved display text.
"""

from __future__ import annotations

import codecs
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
from types import SimpleNamespace

__all__ = ["ERROR_CODES", "WriterError", "write_document"]

MAX_SOURCE_BYTES = 12 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_CAPTURE_LIMIT_CHARS = 64 * 1024
_CHILDREN_FILE_ID = "::"
_RPGMTL_PROJECT_NAME = "ainiee"
_RPGMTL_COMMON_EVENTS_KEY = "data/commonevents.json"
_RPGMTL_MODULES = ("plugins", "plugins.json")
_SEXTRACTOR_MODULES = ("common", "extract_RPGMV", "extract_TXT")
_STEV_MODULE_NAME = "ainiee_backend_writer_stev_jtpp"
_STEV_READER_CLASS = "Jr_Tpp"
_STEV_WRITE_METHOD = "_Jr_Tpp__WriteFile"
_CANONICAL_ARRAY_INDEX = re.compile(r"^(?:0|[1-9][0-9]*)$")
_CHANGE_KEYS = frozenset({"pointer", "source_text", "text"})
_UNPARSED = object()

_CAPABILITIES = {
    "memory_only": True,
    "third_party_write_api": True,
    "isolated_process_required": True,
    "approved_display_text": False,
}

ERROR_CODES = (
    "BACKEND_UNKNOWN",
    "BACKEND_ROOT_INVALID",
    "BACKEND_PATH_INVALID",
    "BACKEND_SOURCE_INVALID",
    "BACKEND_SOURCE_TOO_LARGE",
    "BACKEND_SOURCE_ENCODING_INVALID",
    "BACKEND_SOURCE_JSON_INVALID",
    "BACKEND_CHANGES_INVALID",
    "BACKEND_POINTER_INVALID",
    "BACKEND_POINTER_DUPLICATE",
    "BACKEND_POINTER_UNRESOLVED",
    "BACKEND_SOURCE_TEXT_MISMATCH",
    "BACKEND_UPSTREAM_MISSING",
    "BACKEND_UPSTREAM_FAILURE",
    "BACKEND_FILE_UNSUPPORTED",
    "BACKEND_LOCATOR_UNSUPPORTED",
    "BACKEND_UNAPPROVED_DIFF",
    "BACKEND_OUTPUT_TOO_LARGE",
)


# ---------------------------------------------------------------------------
# BackendWorker (pointer helpers and upstream loaders) import
# ---------------------------------------------------------------------------
def _load_backend_worker_module():
    """Load the sibling ``BackendWorker.py`` when imported outside a package."""
    module_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "BackendWorker.py"
    )
    spec = importlib.util.spec_from_file_location(
        "ainiee_backend_writer_worker", module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(
            "BackendWorker.py is not importable next to BackendWriters.py"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


try:  # regular package import
    from . import BackendWorker
except Exception:  # loaded by file path inside a fresh worker process
    BackendWorker = _load_backend_worker_module()


# ---------------------------------------------------------------------------
# stable errors
# ---------------------------------------------------------------------------
class WriterError(ValueError):
    """Stable failure code raised by :func:`write_document`.

    ``code`` is one of :data:`ERROR_CODES`.  ``detail`` is a short, structural
    hint (change index, upstream exception class, size) and never contains
    source or translated text.
    """

    def __init__(self, code, detail=None):
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


class _RequestedChange:
    """One validated whole-leaf assignment."""

    __slots__ = ("pointer", "source_text", "text", "tokens")

    def __init__(self, pointer, source_text, text, tokens):
        self.pointer = pointer
        self.source_text = source_text
        self.text = text
        self.tokens = tokens


def _short(value, limit=48):
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


# ---------------------------------------------------------------------------
# third-party capture boundary
# ---------------------------------------------------------------------------
class _DiscardingSink(io.TextIOBase):
    """Size-bounded capture sink: upstream output is counted, never kept."""

    def __init__(self):
        self.written = 0

    def writable(self):
        return True

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        if self.written < _CAPTURE_LIMIT_CHARS:
            self.written = min(self.written + len(text), _CAPTURE_LIMIT_CHARS)
        return len(text)

    def flush(self):
        return None


@contextlib.contextmanager
def _third_party_boundary():
    """Suppress and discard upstream stdout/stderr; leave stdin empty.

    The sink keeps no content (so no raw log can leak into a result) and stdin
    is a closed text buffer so an upstream ``input()`` fails instead of
    blocking the worker.
    """
    sink = _DiscardingSink()
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            yield sink
    finally:
        sys.stdin = saved_stdin


def _run_upstream(action, *args, **kwargs):
    """Call third-party code behind the capture boundary.

    A raised exception becomes ``BACKEND_UPSTREAM_FAILURE`` and only the
    exception class name is reported, so upstream diagnostics (which may embed
    document content) are never echoed back.
    """
    try:
        with _third_party_boundary():
            return action(*args, **kwargs)
    except WriterError:
        raise
    except Exception as exc:
        raise WriterError("BACKEND_UPSTREAM_FAILURE", type(exc).__name__) from None


def _drop_foreign_modules(base_dir, module_names):
    """Forget cached upstream modules that came from a different root."""
    prefix = os.path.abspath(base_dir).rstrip("\\/") + os.sep
    for name in module_names:
        module = sys.modules.get(name)
        if module is None:
            continue
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str) or not module_file:
            continue
        if not os.path.abspath(module_file).startswith(prefix):
            sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# input validation
# ---------------------------------------------------------------------------
def _validate_backend_root(backend_root):
    if not isinstance(backend_root, str) or not backend_root.strip():
        raise WriterError("BACKEND_ROOT_INVALID")
    if not os.path.isabs(backend_root):
        raise WriterError("BACKEND_ROOT_INVALID", "not absolute")
    root = os.path.abspath(backend_root)
    if not os.path.isdir(root):
        raise WriterError("BACKEND_ROOT_INVALID", "not a directory")
    return root


def _validate_relative_path(relative_path):
    try:
        return BackendWorker._validate_relative_path(relative_path)
    except WriterError:
        raise
    except Exception:
        raise WriterError("BACKEND_PATH_INVALID") from None


def _decode_source(source):
    """Return ``(source_bytes, document, had_bom, decoded_text)``."""
    if isinstance(source, (bytearray, memoryview)):
        source = bytes(source)
    if not isinstance(source, bytes):
        raise WriterError("BACKEND_SOURCE_INVALID", "source must be bytes")
    if len(source) > MAX_SOURCE_BYTES:
        raise WriterError("BACKEND_SOURCE_TOO_LARGE", f"{len(source)} bytes")
    has_bom = source.startswith(codecs.BOM_UTF8)
    try:
        text = source.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise WriterError("BACKEND_SOURCE_ENCODING_INVALID") from None
    try:
        document = _strict_loads(text)
    except (ValueError, RecursionError):
        raise WriterError("BACKEND_SOURCE_JSON_INVALID") from None
    return source, document, has_bom, text


# ---------------------------------------------------------------------------
# JSON pointers
# ---------------------------------------------------------------------------
def _split_pointer(pointer, index):
    """Validate a non-root RFC 6901 pointer and return its reference tokens."""
    if not pointer.startswith("/"):
        raise WriterError(
            "BACKEND_POINTER_INVALID", f"change[{index}] is not a non-root pointer"
        )
    tokens = pointer.split("/")[1:]
    for token in tokens:
        position = token.find("~")
        while position >= 0:
            if position + 1 >= len(token) or token[position + 1] not in ("0", "1"):
                raise WriterError(
                    "BACKEND_POINTER_INVALID",
                    f"change[{index}] has an invalid ~ escape",
                )
            position = token.find("~", position + 2)
    return tokens


def _decode_token(token):
    return token.replace("~1", "/").replace("~0", "~")


def _walk_pointer(document, tokens, index):
    """Walk the already validated tokens, rejecting non-canonical indexes."""
    node = document
    for token in tokens:
        segment = _decode_token(token)
        if isinstance(node, dict):
            if segment not in node:
                raise WriterError("BACKEND_POINTER_UNRESOLVED", f"change[{index}]")
            node = node[segment]
        elif isinstance(node, list):
            if _CANONICAL_ARRAY_INDEX.match(segment) is None:
                raise WriterError(
                    "BACKEND_POINTER_INVALID",
                    f"change[{index}] has a non-canonical array index",
                )
            position = int(segment)
            if position >= len(node):
                raise WriterError("BACKEND_POINTER_UNRESOLVED", f"change[{index}]")
            node = node[position]
        else:
            raise WriterError("BACKEND_POINTER_UNRESOLVED", f"change[{index}]")
    return node


def _resolve_change(document, pointer, index):
    """Return ``(tokens, leaf_text)`` for a validated, existing string leaf."""
    tokens = _split_pointer(pointer, index)
    walked = _walk_pointer(document, tokens, index)
    resolved = BackendWorker._resolve_pointer(document, pointer)
    if not isinstance(walked, str) or resolved != walked:
        raise WriterError("BACKEND_POINTER_UNRESOLVED", f"change[{index}]")
    return tokens, walked


def _assign_leaf(document, tokens, text):
    """Assign one whole leaf; the path was proven to exist by validation."""
    node = document
    for token in tokens[:-1]:
        segment = _decode_token(token)
        node = node[segment] if isinstance(node, dict) else node[int(segment)]
    last = _decode_token(tokens[-1])
    if isinstance(node, dict):
        node[last] = text
    else:
        node[int(last)] = text


def _normalize_changes(changes, document, expected):
    """Validate the caller's change list and build the expected document."""
    if not isinstance(changes, (list, tuple)):
        raise WriterError("BACKEND_CHANGES_INVALID", "changes must be a list")
    requested = []
    seen = set()
    for index, change in enumerate(changes):
        if not isinstance(change, dict) or set(change.keys()) != _CHANGE_KEYS:
            raise WriterError("BACKEND_CHANGES_INVALID", f"change[{index}] keys")
        pointer = change["pointer"]
        source_text = change["source_text"]
        text = change["text"]
        if (
            not isinstance(pointer, str)
            or not isinstance(source_text, str)
            or not isinstance(text, str)
        ):
            raise WriterError("BACKEND_CHANGES_INVALID", f"change[{index}] values")
        if pointer in seen:
            raise WriterError("BACKEND_POINTER_DUPLICATE", f"change[{index}]")
        seen.add(pointer)
        tokens, resolved = _resolve_change(document, pointer, index)
        if resolved != source_text:
            raise WriterError("BACKEND_SOURCE_TEXT_MISMATCH", f"change[{index}]")
        _assign_leaf(expected, tokens, text)
        requested.append(_RequestedChange(pointer, source_text, text, tokens))
    return requested


# ---------------------------------------------------------------------------
# canonical comparison of the upstream result
# ---------------------------------------------------------------------------
def _canonical_json(value):
    """Type-preserving canonical form of a parsed JSON value."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return f"int({value})"
    if isinstance(value, float):
        if value != value:
            return "float(nan)"
        if value == float("inf"):
            return "float(inf)"
        if value == float("-inf"):
            return "float(-inf)"
        return f"float({value!r})"
    if isinstance(value, str):
        return "str(" + json.dumps(value, ensure_ascii=False) + ")"
    if isinstance(value, (list, tuple)):
        return "list[" + ",".join(_canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        parts = []
        for key in sorted(value.keys(), key=str):
            if not isinstance(key, str):
                raise WriterError(
                    "BACKEND_UNAPPROVED_DIFF", "non-string object key"
                )
            parts.append(
                json.dumps(key, ensure_ascii=False) + ":" + _canonical_json(value[key])
            )
        return "dict{" + ",".join(parts) + "}"
    raise WriterError("BACKEND_UNAPPROVED_DIFF", type(value).__name__)


def _parse_json_bytes(payload):
    try:
        text = payload.decode("utf-8-sig")
    except (AttributeError, UnicodeDecodeError):
        return _UNPARSED
    try:
        return _strict_loads(text)
    except (ValueError, RecursionError):
        return _UNPARSED


def _strict_loads(text):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('DUPLICATE_JSON_KEY')
            result[key]=value
        return result
    def invalid(_):raise ValueError('INVALID_JSON_NUMBER')
    return json.loads(text,object_pairs_hook=unique,parse_constant=invalid)


def _assert_expected_value(produced, expected):
    if _canonical_json(produced) != _canonical_json(expected):
        raise WriterError("BACKEND_UNAPPROVED_DIFF")


def _assert_expected(output_bytes, expected):
    """Comparison gate; never a fallback writer."""
    produced = _parse_json_bytes(output_bytes)
    if produced is _UNPARSED:
        raise WriterError("BACKEND_UNAPPROVED_DIFF", "output is not JSON")
    _assert_expected_value(produced, expected)


def _serialize_document(document, has_bom):
    try:
        payload = json.dumps(
            document, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        # The upstream result cannot be represented as JSON, so it cannot match
        # the expected document either.
        raise WriterError("BACKEND_UNAPPROVED_DIFF", "serialization") from None
    return codecs.BOM_UTF8 + payload if has_bom else payload


def _finalize_mutated_document(document, expected, source_bytes, has_bom, changes):
    """Verify an in-memory result and turn it into output bytes.

    When every requested assignment is a no-op the caller's original bytes are
    returned untouched (no reformatting) after the upstream result has been
    proven equivalent to the expected document.  Otherwise the mutated document
    is serialized and its parsed form must equal the expected document exactly.
    """
    if all(change.text == change.source_text for change in changes):
        _assert_expected_value(document, expected)
        return source_bytes
    output_bytes = _serialize_document(document, has_bom)
    _assert_expected(output_bytes, expected)
    return output_bytes


def _unique_record(records, change, index):
    """Find the single proven whole-string record for one requested pointer."""
    matches = []
    for record in records:
        if not isinstance(record, dict):
            continue
        locator = record.get("locator")
        if not isinstance(locator, dict):
            continue
        if record.get("candidate_pointers") != [change.pointer]:
            continue
        if locator.get("whole_string") is not True:
            continue
        matches.append(record)
    if len(matches) != 1:
        raise WriterError("BACKEND_LOCATOR_UNSUPPORTED", f"change[{index}]")
    if matches[0].get("text") != change.source_text:
        raise WriterError("BACKEND_LOCATOR_UNSUPPORTED", f"change[{index}]")
    return matches[0]


# ---------------------------------------------------------------------------
# stev: Jr_Tpp memory writer
# ---------------------------------------------------------------------------
def _stev_address_tokens(address, basename):
    if address == basename:
        return []
    prefix = basename + "\\"
    if not address.startswith(prefix):
        return None
    return address[len(prefix):].split("\\")


def _write_stev(
    *,
    backend_root,
    relative_path,
    source_bytes,
    document,
    decoded_text,
    has_bom,
    expected,
    changes,
):
    jtpp_path = os.path.join(backend_root, "jtpp.py")
    if not os.path.isfile(jtpp_path):
        raise WriterError("BACKEND_UPSTREAM_MISSING", "jtpp.py")
    records, _capabilities = _run_upstream(
        BackendWorker._extract_stev,
        backend_root,
        relative_path,
        document,
        decoded_text,
    )
    module = _run_upstream(
        BackendWorker._load_module, jtpp_path, _STEV_MODULE_NAME
    )
    reader_class = getattr(module, _STEV_READER_CLASS, None)
    if reader_class is None:
        raise WriterError("BACKEND_UPSTREAM_FAILURE", _STEV_READER_CLASS)
    reader = _run_upstream(
        reader_class, {"ja": False, "ReadCode": [], "sumcode": [], "sptext": {}}
    )
    write_file = getattr(reader, _STEV_WRITE_METHOD, None)
    if not callable(write_file):
        raise WriterError("BACKEND_UPSTREAM_FAILURE", _STEV_WRITE_METHOD)

    basename = relative_path.rsplit("/", 1)[-1]
    working = document
    locators = []
    for index, change in enumerate(changes):
        record = _unique_record(records, change, index)
        locator = record["locator"]
        if locator.get("merge_count") not in (None, 1):
            raise WriterError(
                "BACKEND_LOCATOR_UNSUPPORTED", f"change[{index}] merged text"
            )
        address = locator.get("address")
        if not isinstance(address, str):
            raise WriterError("BACKEND_LOCATOR_UNSUPPORTED", f"change[{index}]")
        tokens = _stev_address_tokens(address, basename)
        if not tokens:
            raise WriterError("BACKEND_LOCATOR_UNSUPPORTED", f"change[{index}]")
        derived = "".join(
            "/" + BackendWorker._escape_pointer_segment(token) for token in tokens
        )
        expected_tokens = [_decode_token(token) for token in change.tokens]
        if derived != change.pointer or tokens != expected_tokens:
            raise WriterError("BACKEND_LOCATOR_UNSUPPORTED", f"change[{index}]")
        code = locator.get("code")
        if not isinstance(code, str):
            code = None
        # Dir is the proven locator address; length is 1 so no list element is
        # ever marked for deletion and no cleanup helper is called.
        working = _run_upstream(
            write_file,
            working,
            change.source_text,
            change.text,
            list(tokens),
            1,
            code,
        )
        locators.append(
            {
                "pointer": change.pointer,
                "address": address,
                "code": code,
                "merge_count": locator.get("merge_count"),
            }
        )
    output_bytes = _finalize_mutated_document(
        working, expected, source_bytes, has_bom, changes
    )
    return output_bytes, locators


# ---------------------------------------------------------------------------
# sextractor: extract_RPGMV memory writer
# ---------------------------------------------------------------------------
def _sextractor_owner_key(document, tokens, index):
    """Return the last dictionary key on a validated path, if representable.

    The upstream parser traverses lists under the most recent dictionary field,
    so ``/terms/commands/4`` has to enable ``commands`` even though its final
    token is an array index.  Array steps never replace the owning key, and a
    dictionary key that merely looks numeric is not treated as an array index.
    """
    node = document
    owner = None
    for token in tokens:
        segment = _decode_token(token)
        if isinstance(node, dict):
            if segment not in node:
                raise WriterError("BACKEND_POINTER_UNRESOLVED", f"change[{index}]")
            owner = segment
            node = node[segment]
        elif isinstance(node, list):
            if _CANONICAL_ARRAY_INDEX.match(segment) is None:
                raise WriterError(
                    "BACKEND_POINTER_INVALID",
                    f"change[{index}] has a non-canonical array index",
                )
            position = int(segment)
            if position >= len(node):
                raise WriterError("BACKEND_POINTER_UNRESOLVED", f"change[{index}]")
            node = node[position]
        else:
            raise WriterError("BACKEND_POINTER_UNRESOLVED", f"change[{index}]")
    if isinstance(owner, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", owner):
        return owner
    return None


def _write_sextractor(
    *,
    backend_root,
    relative_path,
    source_bytes,
    document,
    decoded_text,
    has_bom,
    expected,
    changes,
):
    source_root = os.path.join(backend_root, "src")
    engine_file = os.path.join(source_root, "extract_RPGMV.py")
    if not os.path.isfile(engine_file):
        raise WriterError("BACKEND_UPSTREAM_MISSING", "src/extract_RPGMV.py")
    _drop_foreign_modules(source_root, _SEXTRACTOR_MODULES)
    if source_root not in sys.path:sys.path.insert(0,source_root)
    engine = _run_upstream(BackendWorker._import_upstream, "extract_RPGMV")
    # Audited compatibility rules: the upstream table excludes linked 402
    # labels and predates MZ 357. Enable those codes only in this isolated
    # process, and expose requested object keys to its real parser. Every
    # selected ctrl still needs an exact whole-leaf pointer proof below.
    table=engine.EVENT_COMMAND_CODES
    event_literals=set()
    for index,change in enumerate(changes):
        if change.tokens[-2:]!=['parameters','4']:continue
        parent=_walk_pointer(document,change.tokens[:-2],index)
        if not isinstance(parent,dict) or parent.get('code')!=122:continue
        values=parent.get('parameters')
        if (type(parent['code']) is not int or not isinstance(values,list) or len(values)!=5 or
                any(type(value) is not int for value in values[:4]) or values[0]!=values[1] or
                values[0]<=0 or values[2:4]!=[0,4]):
            raise WriterError('BACKEND_LOCATOR_UNSUPPORTED','event literal assignment')
        from ModuleFolders.Domain.GameProject.EventLiteralCodec import decode_literal
        try:decode_literal(change.source_text);decode_literal(change.text)
        except ValueError:raise WriterError('BACKEND_LOCATOR_UNSUPPORTED','event expression is not a string literal') from None
        event_literals.add(change.pointer)
    enabled_codes=(402,357,122) if event_literals else (402,357)
    previous={code:copy.deepcopy(table.get(code)) for code in enabled_codes}
    old_keys=BackendWorker.SEXTRACTOR_EXTRACT_KEY
    extra_keys=set()
    for index,change in enumerate(changes):
        owner_key=_sextractor_owner_key(document,change.tokens,index)
        if owner_key is not None:extra_keys.add(owner_key)
    try:
        table[402]=['Choice branch label',True,True]
        table[357]=['MZ plugin command',True,True]
        if event_literals:table[122]=['Approved event display literal',True,True]
        BackendWorker.SEXTRACTOR_EXTRACT_KEY=','.join(sorted(set(old_keys.split(','))|extra_keys))
        records,_capabilities=_run_upstream(BackendWorker._extract_sextractor,
            backend_root,relative_path,document,decoded_text)
    finally:
        BackendWorker.SEXTRACTOR_EXTRACT_KEY=old_keys
        for code,value in previous.items():
            if value is None:table.pop(code,None)
            else:table[code]=value
    replace_once = getattr(engine, "replaceOnceImp", None)
    replace_end = getattr(engine, "replaceEndImp", None)
    if not callable(replace_once) or not callable(replace_end):
        raise WriterError("BACKEND_UPSTREAM_FAILURE", "extract_RPGMV write API")

    ctrls = []
    translations = []
    locators = []
    for index, change in enumerate(changes):
        record = _unique_record(records, change, index)
        ctrl = record["locator"].get("ctrl")
        if not isinstance(ctrl, dict) or not isinstance(ctrl.get("pos"), (list, tuple)):
            raise WriterError("BACKEND_LOCATOR_UNSUPPORTED", f"change[{index}]")
        snapshot = copy.deepcopy(ctrl)
        ctrls.append(snapshot)
        translations.append(change.text)
        locators.append({"pointer": change.pointer, "ctrl": snapshot,
            'adapter_rules':['linked-choice-402','mz-plugin-357','approved-field-keys']+
                (['approved-event-literal-122'] if change.pointer in event_literals else [])})
    # The upstream API mutates the document in memory and returns no bytes.
    _run_upstream(replace_once, document, ctrls, translations)
    _run_upstream(replace_end, document)
    output_bytes = _finalize_mutated_document(
        document, expected, source_bytes, has_bom, changes
    )
    return output_bytes, locators


# ---------------------------------------------------------------------------
# rpgmtl: per-occurrence LocatedString project mapper
# ---------------------------------------------------------------------------
class LocatedString(str):
    """Source string that carries the JSON pointer of its own leaf.

    Plain attributes are used on purpose: ``str`` is a variable-size type, so a
    nonempty ``__slots__`` declaration would be rejected at class creation.
    """

    def __new__(cls, value, pointer=None):
        located = super().__new__(cls, value)
        located.pointer = pointer
        return located

    def __deepcopy__(self, memo):
        return LocatedString(str(self), self.pointer)


def _locate_strings(node, pointer):
    """Wrap every non-empty string leaf; keys and numbers stay untouched."""
    if isinstance(node, str):
        return node if node == "" else LocatedString(node, pointer)
    if isinstance(node, list):
        return [
            _locate_strings(child, pointer + "/" + str(position))
            for position, child in enumerate(node)
        ]
    if isinstance(node, dict):
        return {
            key: _locate_strings(
                child, pointer + "/" + BackendWorker._escape_pointer_segment(key)
            )
            for key, child in node.items()
        }
    return node


class _LocalJSONProxy:
    """Scoped stand-in for ``plugins.json``'s ``json`` module.

    ``loads`` hands the plugin the located document (a deep copy per call) so
    its real traversal proves the source pointer of every extracted leaf;
    ``dumps``/``dump`` and every other attribute stay the stdlib
    implementation.  It is installed only around the upstream ``read`` call and
    restored in ``finally`` before writing.
    """

    __slots__ = ("_located",)

    def __init__(self, located_document):
        self._located = located_document

    def loads(self, *args, **kwargs):
        return copy.deepcopy(self._located)

    @staticmethod
    def dumps(value, *args, **kwargs):
        return json.dumps(value, *args, **kwargs)

    @staticmethod
    def dump(value, stream, *args, **kwargs):
        return json.dump(value, stream, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(json, name)


def _import_rpgmtl_plugin(backend_root):
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    return BackendWorker._import_upstream("plugins.json")


def _rpgmtl_file_key(relative_path):
    """Mirror ``PurePath(file_path).relative_to(parent.parent)`` as a key."""
    parts = relative_path.split("/")
    if len(parts) < 2:
        raise WriterError("BACKEND_FILE_UNSUPPORTED", "path has no data folder")
    return "/".join(parts[-2:]).lower()


def _build_rpgmtl_project(groups, relative_path, changes):
    """Build a project mapping with one unique global id per occurrence."""
    if not isinstance(groups, (list, tuple)):
        raise WriterError("BACKEND_UPSTREAM_FAILURE", "plugins.json.read")
    requested = {change.pointer: change for change in changes}
    strings = {}
    files = []
    found = {}
    next_id = 0
    for group_index, group in enumerate(groups):
        if not isinstance(group, (list, tuple)) or not group:
            raise WriterError("BACKEND_LOCATOR_UNSUPPORTED", f"group[{group_index}]")
        label = group[0]
        if not isinstance(label, str):
            raise WriterError("BACKEND_LOCATOR_UNSUPPORTED", f"group[{group_index}]")
        if label.startswith(_CHILDREN_FILE_ID):
            raise WriterError(
                "BACKEND_FILE_UNSUPPORTED", "CommonEvents virtual child groups"
            )
        built = [label]
        for item_index in range(1, len(group)):
            item = group[item_index]
            if not isinstance(item, str):
                raise WriterError(
                    "BACKEND_LOCATOR_UNSUPPORTED",
                    f"group[{group_index}] item[{item_index}]",
                )
            pointer = getattr(item, "pointer", None)
            global_id = next_id
            next_id += 1
            local_translation = None
            modified = 0
            if isinstance(pointer, str) and pointer in requested:
                if pointer in found:
                    raise WriterError(
                        "BACKEND_LOCATOR_UNSUPPORTED", "ambiguous pointer"
                    )
                local_translation = requested[pointer].text
                modified = 1
                found[pointer] = {
                    "pointer": pointer,
                    "group_index": group_index,
                    "item_index": item_index,
                    "global_id": global_id,
                }
            strings[global_id] = [str(item), None, 1, 0]
            built.append([global_id, local_translation, 1, 0, modified])
        files.append(built)
    for change in changes:
        if change.pointer not in found:
            raise WriterError(
                "BACKEND_LOCATOR_UNSUPPORTED",
                "requested pointer was not proven by the traversal",
            )
    return {"strings": strings, "files": {relative_path: files}}, found


def _write_rpgmtl(
    *,
    backend_root,
    relative_path,
    source_bytes,
    document,
    decoded_text,
    has_bom,
    expected,
    changes,
):
    plugin_file = os.path.join(backend_root, "plugins", "json.py")
    if not os.path.isfile(plugin_file):
        raise WriterError("BACKEND_UPSTREAM_MISSING", "plugins/json.py")
    common_events = _rpgmtl_file_key(relative_path) == _RPGMTL_COMMON_EVENTS_KEY
    # The upstream plugin parses JSON text, so it receives the original document
    # bytes without the transport BOM (the BOM is restored on the way out).
    upstream_bytes = (
        source_bytes[len(codecs.BOM_UTF8):] if has_bom else source_bytes
    )
    located = _locate_strings(document, "")
    _drop_foreign_modules(backend_root, _RPGMTL_MODULES)
    module = _run_upstream(_import_rpgmtl_plugin, backend_root)
    plugin_class = getattr(module, "JSON", None)
    if plugin_class is None:
        raise WriterError("BACKEND_UPSTREAM_FAILURE", "plugins.json.JSON")

    plugin = _run_upstream(plugin_class)
    plugin.set_settings({"json_rpgm_multiline": False})
    owner = SimpleNamespace(CHILDREN_FILE_ID=_CHILDREN_FILE_ID, strings={})
    plugin.owner = owner

    original_json = getattr(module, "json", None)
    if original_json is None:
        raise WriterError("BACKEND_UPSTREAM_FAILURE", "plugins.json json module")
    try:
        module.json = _LocalJSONProxy(located)
        groups = _run_upstream(plugin.read, relative_path, upstream_bytes)
    finally:
        module.json = original_json

    if common_events:
        from .RpgmtlCommonMapper import map_common_events
        try:
            mapped = map_common_events(groups, relative_path, document,
                [{'pointer': change.pointer, 'source_text': change.source_text, 'text': change.text} for change in changes])
        except ValueError:
            raise WriterError('BACKEND_LOCATOR_UNSUPPORTED', 'CommonEvents virtual child mapping rejected') from None
        project_strings, found = mapped['project_strings'], mapped['found']
        # The upstream writer walks every enabled virtual child, even when
        # it has no local translation. Limit execution to requested children;
        # unrequested scripts and metadata must remain outside this attempt.
        requested_children = {entry['virtual_child'] for entry in found.values()}
        for child, settings in mapped['project']['files'].items():
            settings['ignored'] = int(child not in requested_children)
        owner.projects = {_RPGMTL_PROJECT_NAME: mapped['project']}
    else:
        project_strings, found = _build_rpgmtl_project(groups, relative_path, changes)
    owner.strings[_RPGMTL_PROJECT_NAME] = project_strings
    # Only local (per occurrence) translations are used; global translations
    # stay None so a repeated source string is never broadcast.
    output_bytes, _modified = _run_upstream(
        plugin.write, _RPGMTL_PROJECT_NAME, relative_path, upstream_bytes
    )
    if not isinstance(output_bytes, (bytes, bytearray)):
        raise WriterError("BACKEND_UPSTREAM_FAILURE", "plugins.json.write")
    output_bytes = bytes(output_bytes)
    if has_bom:
        output_bytes = codecs.BOM_UTF8 + output_bytes
    _assert_expected(output_bytes, expected)
    locators = [found[change.pointer] for change in changes]
    return output_bytes, locators


_BACKENDS = {
    "stev": _write_stev,
    "sextractor": _write_sextractor,
    "rpgmtl": _write_rpgmtl,
}


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def write_document(backend, backend_root, relative_path, source, changes):
    """Apply exact whole-leaf translations through a real third-party API.

    ``source`` is the original document as UTF-8 bytes (an optional BOM is
    preserved in the output).  ``changes`` is a list of
    ``{"pointer", "source_text", "text"}`` mappings with unique non-root JSON
    pointers.  Returns ``{"output_bytes", "sidecar", "capabilities"}`` and
    raises :class:`WriterError` (a ``ValueError``) with a stable code.
    """
    if not isinstance(backend, str) or backend not in _BACKENDS:
        raise WriterError("BACKEND_UNKNOWN", _short(backend))
    root = _validate_backend_root(backend_root)
    path = _validate_relative_path(relative_path)
    source_bytes, document, has_bom, decoded_text = _decode_source(source)
    expected = copy.deepcopy(document)
    requested = _normalize_changes(changes, document, expected)
    sidecar = {
        "backend": backend,
        "relative_path": path,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "bom": has_bom,
        "requested_pointers": [change.pointer for change in requested],
        "locators": [],
    }
    capabilities = dict(_CAPABILITIES)
    if not requested:
        # Nothing was asked for: hand the original bytes back untouched.
        capabilities['third_party_write_api']=False
        return {
            "output_bytes": source_bytes,
            "sidecar": sidecar,
            "capabilities": capabilities,
        }
    output_bytes, locators = _BACKENDS[backend](
        backend_root=root,
        relative_path=path,
        source_bytes=source_bytes,
        document=document,
        decoded_text=decoded_text,
        has_bom=has_bom,
        expected=expected,
        changes=requested,
    )
    if not isinstance(output_bytes, (bytes, bytearray)):
        raise WriterError("BACKEND_UPSTREAM_FAILURE", "output type")
    output_bytes = bytes(output_bytes)
    if len(output_bytes) > MAX_OUTPUT_BYTES:
        raise WriterError("BACKEND_OUTPUT_TOO_LARGE", f"{len(output_bytes)} bytes")
    sidecar["locators"] = locators
    return {
        "output_bytes": output_bytes,
        "sidecar": sidecar,
        "capabilities": capabilities,
    }
