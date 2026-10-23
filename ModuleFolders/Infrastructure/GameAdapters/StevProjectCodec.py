"""Pure ProgramData mapping and round planning for the real Stev directory entry.

This module owns the two data-only halves of the ``stev_project`` worker:

* :func:`effective_config` turns the captured upstream ``config.yaml`` bytes
  into a safe, identity-preserving configuration dict;
* :func:`program_rows` records the *actual* ``Jr_Tpp.ProgramData`` tables after
  the real ``ReadGame``/``LabelName`` calls, expanding the extractor's joined
  address/code vectors without searching documents for equal text;
* :func:`plan_rounds` translates approved ``(relative_path, pointer)`` changes
  into at most one row per ``(file, source text)`` per round, using only raw
  addresses that the extractor itself produced.

Nothing here writes a file, calls an upstream writer, or follows a path value
found in the configuration.  All failures are :class:`CodecError` values with a
stable machine-readable ``code``; details are structural (row/change indexes),
never game text or filesystem paths.
"""

from __future__ import annotations

import copy
import json
import os
import re
import stat
from collections import Counter
from pathlib import Path

__all__ = [
    "CodecError",
    "MAX_CHANGES",
    "MAX_ROUNDS",
    "effective_config",
    "plan_rounds",
    "pointer_tokens",
    "program_rows",
    "validate_changes",
]

ZERO_WIDTH = "\u200B"
ADDRESS_JOIN = "☆↑↓"
COLUMNS = ("原文", "译文", "地址", "标签", "code")
MAX_CHANGES = 100_000
MAX_ROUNDS = 256
MAX_PROGRAM_ROWS = 1_000_000
MAX_CONFIG_BYTES = 16 * 1024 * 1024
MAX_DATA_JSON = 16 * 1024 * 1024

_CANONICAL_INDEX = re.compile(r"^(?:0|[1-9][0-9]*)$")
_MERGE_SUFFIX = re.compile(r"^(?:[1-9][0-9]*)$")
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_CHANGE_KEYS = frozenset({"pointer", "source_text", "text"})
_DOCUMENT_INVALID = object()


class CodecError(ValueError):
    """Stable structural failure raised by this codec.

    ``detail`` is a small structural hint (row/change index, vector kind) and
    never contains source text, translated text or filesystem paths.
    """

    def __init__(self, code, detail=None):
        self.code = str(code)
        self.detail = None if detail is None else str(detail)
        super().__init__(self.code if self.detail is None else f"{self.code}: {self.detail}")


def _fail(code, detail=None):
    raise CodecError(code, detail)


# ---------------------------------------------------------------------------
# captured configuration
# ---------------------------------------------------------------------------
def effective_config(raw: bytes) -> dict:
    """Parse the exact captured upstream config and apply safety overrides.

    The YAML is read with the application's pinned ``yaml.safe_load`` and must be a
    mapping.  A deep copy is returned with every extraction/write-enabling
    switch pinned to an inert value.  Path-valued fields are copied as data and
    never opened or resolved.
    """
    if isinstance(raw, (bytearray, memoryview)):
        raw = bytes(raw)
    if not isinstance(raw, bytes):
        _fail("BACKEND_CONFIG_INVALID", "config bytes")
    if len(raw) > MAX_CONFIG_BYTES:
        _fail("BACKEND_CONFIG_INVALID", "config size")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _fail("BACKEND_CONFIG_INVALID", "config encoding")
    try:
        import yaml
        loaded = yaml.safe_load(text)
    except Exception:
        _fail("BACKEND_CONFIG_INVALID", "config yaml")
    if not isinstance(loaded, dict):
        _fail("BACKEND_CONFIG_INVALID", "config mapping")
    try:
        config = copy.deepcopy(loaded)
    except Exception:
        _fail("BACKEND_CONFIG_INVALID", "config copy")
    overrides = {
        "ja": False,
        "sumcode": [],
        "sptext": {},
        "ReadCode": [],
        "BlackDir": [],
        "BlackCode": [],
        "BlackFiles": [],
        "line_length": 0,
        "mark": 0,
    }
    for key, value in overrides.items():
        config[key] = copy.deepcopy(value)
    return config


# ---------------------------------------------------------------------------
# address/pointer helpers
# ---------------------------------------------------------------------------
def _escape_pointer_segment(segment):
    return str(segment).replace("~", "~0").replace("/", "~1")


def _decode_pointer_segment(segment):
    return segment.replace("~1", "/").replace("~0", "~")


def pointer_tokens(pointer):
    """Validate a non-root RFC 6901 pointer and return its decoded tokens."""
    if not isinstance(pointer, str) or pointer == "" or not pointer.startswith("/"):
        _fail("BACKEND_POINTER_INVALID", "pointer")
    raw_tokens = pointer.split("/")[1:]
    tokens = []
    for token in raw_tokens:
        position = token.find("~")
        while position >= 0:
            if position + 1 >= len(token) or token[position + 1] not in ("0", "1"):
                _fail("BACKEND_POINTER_INVALID", "pointer escape")
            position = token.find("~", position + 2)
        tokens.append(_decode_pointer_segment(token))
    return tokens


def _normalize_table_relative(table_key):
    """Return a safe ``/``-separated data-relative name, or ``None``."""
    if not isinstance(table_key, str) or table_key == "":
        return None
    text = table_key.replace("\\", "/")
    if text.startswith("/") or _DRIVE_PREFIX.match(text):
        return None
    parts = text.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            return None
        if any(ord(character) < 32 for character in part) or ":" in part:
            return None
    return "/".join(parts)


def _split_raw_address(raw):
    """Split one extractor address into ``(base, length)`` when unambiguous."""
    if not isinstance(raw, str) or raw.count(ZERO_WIDTH) != 1:
        return None, None
    base, suffix = raw.split(ZERO_WIDTH, 1)
    if _MERGE_SUFFIX.fullmatch(suffix) is None:
        return None, None
    try:
        length = int(suffix)
    except (TypeError, ValueError):
        return None, None
    if length < 1:
        return None, None
    return base, length


def _address_tokens(base, table_key):
    """Return unambiguous address path tokens, or ``None`` for a null locator."""
    if not isinstance(base, str) or not isinstance(table_key, str):
        return None
    if base == table_key:
        return []
    prefix = table_key + "\\"
    if not base.startswith(prefix):
        return None
    remainder = base[len(prefix):]
    if remainder == "":
        return None
    tokens = remainder.split("\\")
    for token in tokens:
        if token == "":
            return None
        if "\\" in token or ZERO_WIDTH in token or ADDRESS_JOIN in token:
            return None
    return tokens


def _resolve_tokens(document, tokens):
    """Strictly walk dict keys and canonical list indexes."""
    node = document
    for token in tokens:
        if isinstance(node, dict):
            if token not in node:
                return False, None
            node = node[token]
        elif isinstance(node, list):
            if _CANONICAL_INDEX.match(token) is None:
                return False, None
            index = int(token)
            if index >= len(node):
                return False, None
            node = node[index]
        else:
            return False, None
    return True, node


def _injectable_address(base, table_key):
    """Mirror the directory injector's ``split("json\\\\")`` address anchor."""
    if not isinstance(base, str) or not isinstance(table_key, str):
        return False
    if not table_key.endswith(".json"):
        return False
    return base.find("json\\") == len(table_key) - 4


# ---------------------------------------------------------------------------
# source document cache used only for exact address proof
# ---------------------------------------------------------------------------
def _load_document(game_root, relative):
    candidate = Path(game_root) / "data"
    for part in relative.split("/"):
        candidate = candidate / part
    try:
        info = os.lstat(candidate)
    except OSError:
        return _DOCUMENT_INVALID
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or getattr(info, "st_nlink", 1) != 1
        or info.st_size > MAX_DATA_JSON
    ):
        return _DOCUMENT_INVALID
    try:
        with open(candidate, "rb") as handle:
            raw = handle.read(MAX_DATA_JSON + 1)
    except OSError:
        return _DOCUMENT_INVALID
    if len(raw) > MAX_DATA_JSON:
        return _DOCUMENT_INVALID
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _DOCUMENT_INVALID
    try:
        return _strict_loads(text)
    except (ValueError, RecursionError):
        return _DOCUMENT_INVALID


def _strict_loads(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("INVALID_JSON_NUMBER")

    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid)


def _mapped_occurrence(raw, code, table_key, original, game_root, cache):
    """Return one occurrence record for a raw extractor address."""
    base, length = _split_raw_address(raw)
    tokens = _address_tokens(base, table_key)
    relative = _normalize_table_relative(table_key)
    whole = False
    pointer = None
    relative_path = None
    if (
        tokens
        and length == 1
        and relative is not None
        and _injectable_address(base, table_key)
        and isinstance(code, str)
    ):
        document = cache.get(relative)
        if document is None:
            document = _load_document(game_root, relative)
            cache[relative] = document
        if document is not _DOCUMENT_INVALID:
            resolved, value = _resolve_tokens(document, tokens)
            if resolved and isinstance(value, str) and value == original:
                whole = True
                relative_path = "data/" + relative
                pointer = "".join(
                    "/" + _escape_pointer_segment(token) for token in tokens
                )
    occurrence = {
        "relative_path": relative_path,
        "pointer": pointer,
        "address": raw,
        "code": code if isinstance(code, str) else "",
        "length": length,
        "whole_string": whole,
    }
    return occurrence


def _program_row(table_key, values, index_value, game_root, cache):
    original = _text_value(values["原文"], "row original")
    translation = _text_value(values["译文"], "row translation")
    address = _text_value(values["地址"], "row address")
    labels = _text_value(values["标签"], "row labels")
    code = _text_value(values["code"], "row code")
    if index_value != original:
        _fail("BACKEND_PROGRAM_DATA_INVALID", "row index")
    raw_addresses = address.split(ADDRESS_JOIN)
    raw_codes = code.split(",")
    code_vector_matches = len(raw_addresses) == len(raw_codes)
    counts = Counter(raw_addresses)
    occurrences = []
    for position, raw in enumerate(raw_addresses):
        occurrence_code = raw_codes[position] if position < len(raw_codes) else ""
        occurrence = _mapped_occurrence(
            raw, occurrence_code, table_key, original, game_root, cache
        )
        if counts[raw] != 1:
            occurrence["whole_string"] = False
            occurrence["relative_path"] = None
            occurrence["pointer"] = None
        if not code_vector_matches:
            occurrence["whole_string"] = False
            occurrence["relative_path"] = None
            occurrence["pointer"] = None
        occurrences.append(occurrence)
    return {
        "file": table_key,
        "original": original,
        "translation": translation,
        "address": address,
        "labels": labels,
        "code": code,
        "name_label": "Name" in labels.split(","),
        "occurrences": occurrences,
    }


def _text_value(value, label):
    if not isinstance(value, str):
        _fail("BACKEND_PROGRAM_DATA_INVALID", label)
    return str(value)


def program_rows(reader, game_root: Path) -> list[dict]:
    """Record the actual extractor ``ProgramData`` rows and their locators.

    ``reader`` must have already run the real ``ReadGame`` and
    ``LabelName(reader.NameWithout)`` calls.  Each returned occurrence carries
    the extractor's raw address and code; ``relative_path``/``pointer`` are
    filled only when the exact data file at the address parses to the same
    whole string, the merged length is exactly one and the address is
    unambiguous.  Everything else stays a discovery record.
    """
    try:
        root = Path(os.fspath(game_root))
    except (TypeError, ValueError):
        _fail("BACKEND_PROGRAM_DATA_INVALID", "game root")
    program = getattr(reader, "ProgramData", None)
    if not isinstance(program, dict):
        _fail("BACKEND_PROGRAM_DATA_INVALID", "ProgramData")
    cache = {}
    rows = []
    seen_indexes = set()
    for table_key, frame in program.items():
        if not isinstance(table_key, str) or table_key == "":
            _fail("BACKEND_PROGRAM_DATA_INVALID", "table key")
        columns = list(getattr(frame, "columns", ()))
        if columns != list(COLUMNS):
            _fail("BACKEND_PROGRAM_DATA_INVALID", "columns")
        try:
            count = len(frame)
        except TypeError:
            _fail("BACKEND_PROGRAM_DATA_INVALID", "frame")
        for position in range(count):
            try:
                values = frame.iloc[position]
                index_value = frame.index[position]
            except Exception:
                _fail("BACKEND_PROGRAM_DATA_INVALID", "row access")
            row = _program_row(table_key, values, index_value, root, cache)
            identity = (table_key, row["original"])
            if identity in seen_indexes:
                _fail("BACKEND_PROGRAM_DATA_INVALID", "duplicate index")
            seen_indexes.add(identity)
            rows.append(row)
            if len(rows) > MAX_PROGRAM_ROWS:
                _fail("BACKEND_OUTPUT_TOO_LARGE", "rows")
    return rows


# ---------------------------------------------------------------------------
# change validation and round planning
# ---------------------------------------------------------------------------
def _validate_change_relative(relative_path):
    if not isinstance(relative_path, str) or relative_path == "":
        _fail("BACKEND_CHANGES_INVALID", "relative path")
    if "\\" in relative_path:
        _fail("BACKEND_CHANGES_INVALID", "relative path separator")
    if relative_path.startswith("/") or _DRIVE_PREFIX.match(relative_path):
        _fail("BACKEND_CHANGES_INVALID", "relative path absolute")
    for part in relative_path.split("/"):
        if part in ("", ".", ".."):
            _fail("BACKEND_CHANGES_INVALID", "relative path segment")
        if any(ord(character) < 32 for character in part) or ":" in part:
            _fail("BACKEND_CHANGES_INVALID", "relative path character")
    return relative_path


def validate_changes(changes):
    """Validate the exact ``{relative_path: [{pointer, source_text, text}]}`` map.

    Returns a flat, ordered list of validated change dicts.  The empty map is
    valid and later becomes the single real no-change round.
    """
    if not isinstance(changes, dict):
        _fail("BACKEND_CHANGES_INVALID", "changes mapping")
    validated = []
    seen_pointers = set()
    total = 0
    for relative_path, items in changes.items():
        relative = _validate_change_relative(relative_path)
        if not isinstance(items, (list, tuple)):
            _fail("BACKEND_CHANGES_INVALID", "change list")
        for index, change in enumerate(items):
            if not isinstance(change, dict) or set(change.keys()) != _CHANGE_KEYS:
                _fail("BACKEND_CHANGES_INVALID", "change keys")
            pointer = change["pointer"]
            source_text = change["source_text"]
            text = change["text"]
            if (
                not isinstance(pointer, str)
                or not isinstance(source_text, str)
                or not isinstance(text, str)
            ):
                _fail("BACKEND_CHANGES_INVALID", "change values")
            pointer_tokens(pointer)
            identity = (relative, pointer)
            if identity in seen_pointers:
                _fail("BACKEND_POINTER_DUPLICATE", f"change[{index}]")
            seen_pointers.add(identity)
            if text == "":
                _fail("BACKEND_EMPTY_TRANSLATION_UNSUPPORTED", f"change[{index}]")
            total += 1
            if total > MAX_CHANGES:
                _fail("BACKEND_CHANGES_INVALID", "change count")
            validated.append(
                {
                    "relative_path": relative,
                    "pointer": pointer,
                    "source_text": source_text,
                    "text": text,
                }
            )
    return validated


def _row_index(rows):
    """Map ``(relative_path, pointer)`` to proven occurrence candidates."""
    if not isinstance(rows, (list, tuple)):
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "rows")
    index = {}
    for row_number, row in enumerate(rows):
        if not isinstance(row, dict):
            _fail("BACKEND_LOCATOR_UNSUPPORTED", f"row[{row_number}]")
        table_key = row.get("file")
        original = row.get("original")
        address = row.get("address")
        code_vector = row.get("code")
        labels = row.get("labels", "")
        occurrences = row.get("occurrences")
        if (
            not isinstance(table_key, str)
            or not isinstance(original, str)
            or not isinstance(address, str)
            or not isinstance(code_vector, str)
            or not isinstance(labels, str)
            or not isinstance(occurrences, list)
        ):
            _fail("BACKEND_LOCATOR_UNSUPPORTED", f"row[{row_number}]")
        for occurrence_number, occurrence in enumerate(occurrences):
            if not isinstance(occurrence, dict):
                _fail(
                    "BACKEND_LOCATOR_UNSUPPORTED",
                    f"occurrence[{row_number}:{occurrence_number}]",
                )
            if occurrence.get("whole_string") is not True:
                continue
            relative = occurrence.get("relative_path")
            pointer = occurrence.get("pointer")
            if not isinstance(relative, str) or not isinstance(pointer, str):
                _fail(
                    "BACKEND_LOCATOR_UNSUPPORTED",
                    f"occurrence[{row_number}:{occurrence_number}]",
                )
            index.setdefault((relative, pointer), []).append((row, occurrence))
    return index


def _plan_item(row, occurrence, relative, change):
    table_key = row["file"]
    expected_relative = "data/" + table_key.replace("\\", "/")
    if expected_relative != relative:
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "table owner")
    addresses = row["address"].split(ADDRESS_JOIN)
    codes = row["code"].split(",")
    if len(addresses) != len(codes):
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "address vector")
    raw_address = occurrence["address"]
    occurrence_code = occurrence["code"]
    if not isinstance(raw_address, str) or not isinstance(occurrence_code, str):
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "address")
    if raw_address.count(ZERO_WIDTH) != 1:
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "address ambiguity")
    if addresses.count(raw_address) != 1:
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "address ambiguity")
    position = addresses.index(raw_address)
    if codes[position] != occurrence["code"]:
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "code vector")
    if occurrence["length"] != 1 or type(occurrence["length"]) is not int:
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "merged address")
    if not raw_address.endswith(ZERO_WIDTH + "1"):
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "address length")
    base, parsed_length = _split_raw_address(raw_address)
    tokens = _address_tokens(base, table_key)
    if (
        parsed_length != 1
        or not tokens
        or not _injectable_address(base, table_key)
    ):
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "address delimiter")
    derived_pointer = "".join(
        "/" + _escape_pointer_segment(token) for token in tokens
    )
    if derived_pointer != change["pointer"]:
        _fail("BACKEND_LOCATOR_UNSUPPORTED", "pointer ownership")
    if row["original"] != change["source_text"]:
        _fail("BACKEND_SOURCE_TEXT_MISMATCH", "source text")
    return {
        "relative_path": relative,
        "file": table_key,
        "pointer": change["pointer"],
        "source_text": change["source_text"],
        "text": change["text"],
        "address": raw_address,
        "code": occurrence["code"],
        "labels": row.get("labels", ""),
    }


def plan_rounds(rows, changes: dict[str, list[dict]]) -> list[list[dict]]:
    """Plan real injector rounds for exactly proven occurrences.

    Every requested ``(relative_path, pointer)`` must resolve to exactly one
    whole-string occurrence whose raw address/code vector proves the original
    text.  Changes are partitioned so a round never carries two different
    translations for the same ``(file, source text)`` pair, which would make
    the upstream extractor broadcast one translation to every duplicate.
    """
    validated = validate_changes(changes)
    if not validated:
        return [[]]
    index = _row_index(rows)
    planned = []
    for change in validated:
        identity = (change["relative_path"], change["pointer"])
        matches = index.get(identity, [])
        if len(matches) != 1:
            if len(matches) > 1:
                _fail("BACKEND_LOCATOR_UNSUPPORTED", "duplicate occurrence")
            _fail("BACKEND_LOCATOR_UNSUPPORTED", "missing occurrence")
        row, occurrence = matches[0]
        planned.append(
            _plan_item(row, occurrence, change["relative_path"], change)
        )
    if not planned:
        return [[]]
    rounds = []
    for item in planned:
        identity = (item["relative_path"], item["source_text"])
        for round_items, used in rounds:
            if identity not in used:
                used.add(identity)
                round_items.append(item)
                break
        else:
            if len(rounds) >= MAX_ROUNDS:
                _fail("BACKEND_CHANGES_INVALID", "round count")
            rounds.append(([item], {identity}))
    return [round_items for round_items, _used in rounds]
