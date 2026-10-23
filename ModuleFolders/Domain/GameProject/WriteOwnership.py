"""Pure physical-address ownership checks for game-project write plans.

This module deliberately performs no file I/O and resolves no values.  It only
answers whether the occurrence addresses in a batch can have one writer each.
Recognized locator metadata is not part of a physical address.  It is ignored
for overlap detection, except for the image-region identity fields, which are
validated as a physical address.  Unrecognized locator fields are rejected.
"""
from __future__ import annotations

import unicodedata
from bisect import bisect_left

from .Models import Issue

__all__ = ["ownership_issues"]

_JSON_SUFFIX = ".json"
_JS_SUFFIX = ".js"
_IMAGE_SUFFIXES = (".png", ".png_", ".rpgmvp")
_IMAGE_ADAPTER = "image-region"
_IMAGE_POINTER_PREFIX = "region/"
_IMAGE_FIELDS = frozenset(("region_id", "pointer", "source_sha256", "box"))
_JSON_FIELDS = frozenset(("pointer", "value_codec", "raw_expression", "note_tag", "raw_note", "note_group", "note_last_wins", "event_script_span", "span_text"))
_JS_FIELDS = frozenset(
    (
        "start",
        "end",
        "object_path",
        "property_path",
        "expected",
        "source_sha256",
        "scope_function",
        "property_fields",
        "static_text",
        "node_kind",
        "literal_path",
        "json_steps",
        "json_hashes",
        "json_types",
        "script_span",
        "source_span_id",
        "text_affixes",
    )
)
_JS_IMAGE_MARKERS = frozenset(("region_id", "box"))
_MAX_IMAGE_REGIONS_PER_FILE = 500


class _JsonNode:
    """A token trie node for JSON pointer ownership."""

    __slots__ = ("children", "owner", "descendant_owner")

    def __init__(self):
        self.children = {}
        self.owner = None
        self.descendant_owner = None


class _JsIntervalIndex:
    """An online interval index over compressed start coordinates.

    A prior interval overlaps a new [start, end) when either its start is in
    [start, end), or its start is before start and its end is after start.
    The segment tree answers both queries in O(log n) while retaining one
    representative owner for each query.
    """

    __slots__ = ("starts", "_positions", "_size", "_max_end", "_owners")

    def __init__(self, starts):
        self.starts = starts
        self._positions = {value: index for index, value in enumerate(starts)}
        size = 1
        while size < len(starts):
            size <<= 1
        self._size = size
        self._max_end = [-1] * (2 * size)
        self._owners = [None] * (2 * size)

    def find_conflict(self, start, end):
        position = self._positions[start]

        max_end, owner = self._prefix_max_end(position)
        if max_end > start:
            return owner

        right = bisect_left(self.starts, end)
        if position < right:
            return self._first_owner(position, right)
        return None

    def add(self, start, end, owner):
        position = self._positions[start]
        node = self._size + position
        if end > self._max_end[node]:
            self._max_end[node] = end
            self._owners[node] = owner

        node >>= 1
        while node:
            left = node << 1
            right = left | 1
            left_end = self._max_end[left]
            right_end = self._max_end[right]
            if left_end >= right_end:
                self._max_end[node] = left_end
                self._owners[node] = self._owners[left]
            else:
                self._max_end[node] = right_end
                self._owners[node] = self._owners[right]
            node >>= 1

    def _prefix_max_end(self, right):
        left = self._size
        right += self._size
        best_end = -1
        best_owner = None
        while left < right:
            if left & 1:
                end = self._max_end[left]
                if end > best_end:
                    best_end = end
                    best_owner = self._owners[left]
                left += 1
            if right & 1:
                right -= 1
                end = self._max_end[right]
                if end > best_end:
                    best_end = end
                    best_owner = self._owners[right]
            left >>= 1
            right >>= 1
        return best_end, best_owner

    def _first_owner(self, left, right):
        left += self._size
        right += self._size
        while left < right:
            if left & 1:
                owner = self._owners[left]
                if owner is not None:
                    return owner
                left += 1
            if right & 1:
                right -= 1
                owner = self._owners[right]
                if owner is not None:
                    return owner
            left >>= 1
            right >>= 1
        return None


def ownership_issues(units) -> tuple[Issue, ...]:
    """Return deterministic invalid-locator and ownership-conflict issues.

    Each issue is tied to an occurrence (or to a unit with no occurrences).
    Valid but conflicting claims still take part in later ownership checks so
    that each incoming claim receives at most one representative conflict.
    """
    if units is None:
        return ()
    try:
        unit_iterator = iter(units)
    except TypeError:
        return ()

    sequence = 0
    issues = []
    claims = []

    for unit in unit_iterator:
        unit_id = _as_text(getattr(unit, "unit_id", ""))
        raw_occurrences = getattr(unit, "occurrences", None)
        if raw_occurrences is None:
            occurrences = []
        else:
            try:
                occurrences = list(raw_occurrences)
            except TypeError:
                occurrences = []

        if not occurrences:
            issues.append(
                (
                    sequence,
                    _invalid_issue(
                        unit_id=unit_id,
                        path="",
                        kind="unit",
                        occurrence_id="",
                        reason="no_occurrences",
                    ),
                )
            )
            sequence += 1
            continue

        for occurrence in occurrences:
            claim, issue = _validate_occurrence(unit_id, occurrence)
            if issue is not None:
                issues.append((sequence, issue))
            else:
                claim["sequence"] = sequence
                claims.append(claim)
            sequence += 1

    # Coordinates are collected once so interval queries can remain online in
    # original occurrence order while still taking O(log n) time.
    starts_by_file = {}
    for claim in claims:
        if claim["kind"] != "js":
            continue
        file_key = claim["file"]
        starts = starts_by_file.get(file_key)
        if starts is None:
            starts = set()
            starts_by_file[file_key] = starts
        starts.add(claim["start"])
    interval_indexes = {
        file_key: _JsIntervalIndex(sorted(starts))
        for file_key, starts in starts_by_file.items()
    }

    script_starts={}
    for claim in claims:
        if 'script_range' in claim:
            key=_script_key(claim)
            script_starts.setdefault(key,set()).add(claim['script_range'][0])
    script_indexes={key:_JsIntervalIndex(sorted(starts)) for key,starts in script_starts.items()}
    json_roots = {};encoded_roots={}
    image_files = {}

    for claim in claims:
        kind = claim["kind"]
        other = None

        if kind == "json":
            file_key = claim["file"]
            root = json_roots.get(file_key)
            if root is None:
                root = _JsonNode()
                json_roots[file_key] = root
            other = _json_conflict(root, claim["tokens"])
            _json_insert(root, claim["tokens"], claim)

        elif kind == "js":
            file_key = claim["file"]
            index = interval_indexes[file_key]
            other = index.find_conflict(claim["start"], claim["end"])
            # Disjoint decoded leaves in the same literal share one physical writer.
            if (other is not None and 'json_tokens' in claim and 'json_tokens' in other and
                    (claim['start'],claim['end'])==(other['start'],other['end'])):
                other=None
            index.add(claim["start"], claim["end"], claim)
            if 'json_tokens' in claim:
                key=(file_key,claim['start'],claim['end'])
                root=encoded_roots.setdefault(key,_JsonNode())
                logical=_json_conflict(root,claim['json_tokens']);_json_insert(root,claim['json_tokens'],claim)
                if other is None:other=logical

        else:
            file_key = claim["file"]
            state = image_files.get(file_key)
            if state is None:
                state = {"count": 0, "by_id": {}, "boxes": []}
                image_files[file_key] = state

            if state["count"] >= _MAX_IMAGE_REGIONS_PER_FILE:
                issues.append(
                    (
                        claim["sequence"],
                        _invalid_claim_issue(claim, "image_region_limit"),
                    )
                )
                continue

            state["count"] += 1
            region_id = claim["region_id"]
            x, y, width, height = claim["box"]

            other = state["by_id"].get(region_id)
            if other is None:
                for (
                    other_x,
                    other_y,
                    other_width,
                    other_height,
                    other_claim,
                ) in state["boxes"]:
                    if (
                        x < other_x + other_width
                        and other_x < x + width
                        and y < other_y + other_height
                        and other_y < y + height
                    ):
                        other = other_claim
                        break

            if region_id not in state["by_id"]:
                state["by_id"][region_id] = claim
            state["boxes"].append((x, y, width, height, claim))

        if 'script_range' in claim:
            inner=script_indexes[_script_key(claim)];start,end=claim['script_range']
            conflict=inner.find_conflict(start,end);inner.add(start,end,claim)
            if other is None:other=conflict
        if other is not None:
            issues.append((claim["sequence"], _conflict_issue(claim, other)))

    issues.sort(key=lambda item: item[0])
    return tuple(issue for _, issue in issues)


def _script_key(claim):
    if claim['kind']=='json':return ('json',claim['file'],claim['script_path'])
    return ('js',claim['file'],claim['start'],claim['end'],claim['script_path'])


def _validate_occurrence(unit_id, occurrence):
    occurrence_id = _as_text(getattr(occurrence, "occurrence_id", ""))
    raw_path = getattr(occurrence, "relative_path", None)
    path_text = raw_path if isinstance(raw_path, str) else ""
    adapter_id = getattr(occurrence, "adapter_id", None)
    locator = getattr(occurrence, "locator", None)

    kind_hint = _kind_hint(adapter_id, raw_path)
    if not isinstance(locator, dict):
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path_text,
            kind=kind_hint,
            occurrence_id=occurrence_id,
            reason="locator_not_object",
        )

    file_key, path_error = _normalize_relative_path(raw_path)
    if path_error is not None:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path_text,
            kind=kind_hint,
            occurrence_id=occurrence_id,
            reason=path_error,
        )

    kind_hint = _kind_hint(adapter_id, file_key)
    if adapter_id == _IMAGE_ADAPTER:
        return _image_claim(
            unit_id, path_text, file_key, occurrence_id, locator
        )
    if file_key.endswith(_JSON_SUFFIX):
        return _json_claim(
            unit_id, path_text, file_key, occurrence_id, locator
        )
    if file_key.endswith(_JS_SUFFIX):
        return _js_claim(
            unit_id, path_text, file_key, occurrence_id, locator
        )

    return None, _invalid_issue(
        unit_id=unit_id,
        path=path_text,
        kind=kind_hint,
        occurrence_id=occurrence_id,
        reason="unsupported_file_type",
    )


def _json_claim(unit_id, path, file_key, occurrence_id, locator):
    if any(
        key in locator
        for key in ("start", "end", "region_id", "box", "source_sha256")
    ):
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="json",
            occurrence_id=occurrence_id,
            reason="mixed_locator_kinds",
        )
    if set(locator) - _JSON_FIELDS:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="json",
            occurrence_id=occurrence_id,
            reason="unknown_locator_fields",
        )
    if "pointer" not in locator:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="json",
            occurrence_id=occurrence_id,
            reason="json_pointer_missing",
        )

    tokens, pointer_error = _parse_json_pointer(locator["pointer"])
    if pointer_error is not None:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="json",
            occurrence_id=occurrence_id,
            reason=pointer_error,
        )

    extra={}
    if locator.get('value_codec')=='event-js-span-v1' or any(k in locator for k in ('event_script_span','span_text')):
        try:
            from .EventScriptSpan import validate_locator
            _,span,_=validate_locator(locator)
            extra={'script_path':tokens,'script_range':(span['start'],span['end'])}
            tokens+=('event-script-span',str(span['start'])+':'+str(span['end']))
        except (ValueError,TypeError):
            return None,_invalid_issue(unit_id=unit_id,path=path,kind='json',occurrence_id=occurrence_id,reason='invalid_event_script_span')
    if 'note_group' in locator:
        try:
            from .NoteTagText import validate_locator
            validate_locator(path,locator)
            tokens+=('note-tag-value',locator['note_tag'])
        except (ValueError,TypeError):
            return None,_invalid_issue(unit_id=unit_id,path=path,kind='json',occurrence_id=occurrence_id,reason='invalid_note_group')
    return {
        "kind": "json",
        "unit_id": unit_id,
        "path": path,
        "occurrence_id": occurrence_id,
        "file": file_key,
        "tokens": tokens,
        **extra,
    }, None


def _js_claim(unit_id, path, file_key, occurrence_id, locator):
    if "pointer" in locator or any(key in locator for key in _JS_IMAGE_MARKERS):
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="js",
            occurrence_id=occurrence_id,
            reason="mixed_locator_kinds",
        )
    if set(locator) - _JS_FIELDS:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="js",
            occurrence_id=occurrence_id,
            reason="unknown_locator_fields",
        )
    if "start" not in locator or "end" not in locator:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="js",
            occurrence_id=occurrence_id,
            reason="js_interval_missing",
        )

    start = locator["start"]
    end = locator["end"]
    if type(start) is not int or type(end) is not int:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="js",
            occurrence_id=occurrence_id,
            reason="js_interval_not_integer",
        )
    if start < 0 or start >= end:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="js",
            occurrence_id=occurrence_id,
            reason="js_interval_bounds",
        )

    extra={}
    if 'json_steps' in locator:
        from .EncodedJsonText import ownership_tokens,script_span
        try:
            extra['json_tokens']=ownership_tokens(locator['json_steps'])
            if 'script_span' in locator:
                span=script_span(locator['script_span'])
                extra['script_path']=extra['json_tokens'];extra['script_range']=(span['start'],span['end'])
                extra['json_tokens']+=(('script',''),('range',str(span['start'])+':'+str(span['end'])))
        except ValueError:
            return None,_invalid_issue(unit_id=unit_id,path=path,kind='js',occurrence_id=occurrence_id,reason='invalid_json_steps')
    return {
        "kind": "js",
        "unit_id": unit_id,
        "path": path,
        "occurrence_id": occurrence_id,
        "file": file_key,
        "start": start,
        "end": end,
        **extra,
    }, None


def _image_claim(unit_id, path, file_key, occurrence_id, locator):
    if not file_key.endswith(_IMAGE_SUFFIXES):
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="image-region",
            occurrence_id=occurrence_id,
            reason="unsupported_image_file_type",
        )
    if "start" in locator or "end" in locator:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="image-region",
            occurrence_id=occurrence_id,
            reason="mixed_locator_kinds",
        )
    if set(locator) - _IMAGE_FIELDS:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="image-region",
            occurrence_id=occurrence_id,
            reason="unknown_locator_fields",
        )
    if not _IMAGE_FIELDS.issubset(locator):
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="image-region",
            occurrence_id=occurrence_id,
            reason="image_fields_missing",
        )

    region_id = locator["region_id"]
    if not _is_hex(region_id, 32, lowercase=True):
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="image-region",
            occurrence_id=occurrence_id,
            reason="image_region_id_invalid",
        )
    if locator["pointer"] != _IMAGE_POINTER_PREFIX + region_id:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="image-region",
            occurrence_id=occurrence_id,
            reason="image_pointer_invalid",
        )
    if not _is_hex(locator["source_sha256"], 64):
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="image-region",
            occurrence_id=occurrence_id,
            reason="image_source_sha256_invalid",
        )

    box = locator["box"]
    if type(box) is not list or len(box) != 4:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="image-region",
            occurrence_id=occurrence_id,
            reason="image_box_shape_invalid",
        )
    if any(type(value) is not int for value in box):
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="image-region",
            occurrence_id=occurrence_id,
            reason="image_box_not_integer",
        )

    x, y, width, height = box
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None, _invalid_issue(
            unit_id=unit_id,
            path=path,
            kind="image-region",
            occurrence_id=occurrence_id,
            reason="image_box_bounds_invalid",
        )

    return {
        "kind": "image-region",
        "unit_id": unit_id,
        "path": path,
        "occurrence_id": occurrence_id,
        "file": file_key,
        "region_id": region_id,
        "box": (x, y, width, height),
    }, None


def _parse_json_pointer(pointer):
    if not isinstance(pointer, str):
        return None, "json_pointer_not_string"
    if not pointer:
        return None, "json_pointer_root_unsupported"
    if not pointer.startswith("/"):
        return None, "json_pointer_leading_slash_missing"

    tokens = []
    for raw_token in pointer[1:].split("/"):
        token = []
        index = 0
        while index < len(raw_token):
            character = raw_token[index]
            if character != "~":
                token.append(character)
                index += 1
                continue
            if index + 1 >= len(raw_token) or raw_token[index + 1] not in "01":
                return None, "json_pointer_escape_invalid"
            token.append("~" if raw_token[index + 1] == "0" else "/")
            index += 2

        decoded = "".join(token)
        if decoded in (".", ".."):
            return None, "json_pointer_dot_component"
        tokens.append(decoded)

    return tuple(tokens), None


def _json_conflict(root, tokens):
    node = root
    for token in tokens:
        if node.owner is not None:
            return node.owner
        node = node.children.get(token)
        if node is None:
            return None

    if node.owner is not None:
        return node.owner
    return node.descendant_owner


def _json_insert(root, tokens, claim):
    node = root
    for token in tokens:
        if node.descendant_owner is None:
            node.descendant_owner = claim
        child = node.children.get(token)
        if child is None:
            child = _JsonNode()
            node.children[token] = child
        node = child

    if node.descendant_owner is None:
        node.descendant_owner = claim
    if node.owner is None:
        node.owner = claim


def _normalize_relative_path(value):
    if not isinstance(value, str):
        return None, "path_not_string"
    if not value:
        return None, "path_empty"

    normalized = value.replace("\\", "/")
    if normalized.startswith("/"):
        return None, "path_absolute_or_unc"
    if len(normalized) >= 2 and normalized[1] == ":":
        return None, "path_drive"

    for component in normalized.split("/"):
        if not component:
            return None, "path_empty_component"
        if component == ".":
            return None, "path_dot_component"
        if component == "..":
            return None, "path_dotdot_component"
        if ":" in component:
            return None, "path_colon"
        if any(unicodedata.category(character) == "Cc" for character in component):
            return None, "path_control_character"
        if component.endswith((" ", ".")):
            return None, "path_trailing_dot_or_space"

    return normalized.casefold(), None


def _kind_hint(adapter_id, path):
    if adapter_id == _IMAGE_ADAPTER:
        return "image-region"
    if isinstance(path, str):
        candidate = path.replace("\\", "/").casefold()
        if candidate.endswith(_JSON_SUFFIX):
            return "json"
        if candidate.endswith(_JS_SUFFIX):
            return "js"
    return "unknown"


def _is_hex(value, length, lowercase=False):
    if not isinstance(value, str) or len(value) != length:
        return False
    allowed = "0123456789abcdef" if lowercase else "0123456789abcdefABCDEF"
    return all(character in allowed for character in value)


def _as_text(value):
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _invalid_claim_issue(claim, reason):
    return _invalid_issue(
        unit_id=claim["unit_id"],
        path=claim["path"],
        kind=claim["kind"],
        occurrence_id=claim["occurrence_id"],
        reason=reason,
    )


def _invalid_issue(unit_id, path, kind, occurrence_id, reason):
    return Issue(
        code="WRITE_LOCATOR_INVALID",
        severity="error",
        message="Invalid write ownership locator.",
        unit_id=unit_id,
        path=path,
        details={
            "kind": kind,
            "occurrence_id": occurrence_id,
            "reason": reason,
        },
    )


def _conflict_issue(current, other):
    return Issue(
        code="WRITE_OWNERSHIP_CONFLICT",
        severity="error",
        message="Write ownership conflict.",
        unit_id=current["unit_id"],
        path=current["path"],
        details={
            "kind": current["kind"],
            "occurrence_id": current["occurrence_id"],
            "other_unit_id": other["unit_id"],
            "other_occurrence_id": other["occurrence_id"],
            "address": _address_descriptor(current),
        },
    )


def _address_descriptor(claim):
    if claim["kind"] == "json":
        return {
            "file": claim["file"],
            "tokens": list(claim["tokens"]),
        }
    if claim["kind"] == "js":
        return {
            "file": claim["file"],
            "start": claim["start"],
            "end": claim["end"],
        }
    x, y, width, height = claim["box"]
    return {
        "file": claim["file"],
        "region_id": claim["region_id"],
        "box": [x, y, width, height],
    }
