"""Pure positional helpers for bridging RPGMTL's JavaScript reader.

The real RPGMTL reader slices a decoded source string and normalizes a few
escape spellings with ``str.replace``.  This module keeps those slices tied to
their original character positions without relying on string equality.
"""
from __future__ import annotations

__all__ = ["TrackedJs", "encode_translation", "map_js_groups"]

_INVALID_PREFIX = "RPGMTL_JS_MAPPING_INVALID"
_BOM = b"\xef\xbb\xbf"


def _invalid(detail: str) -> None:
    raise ValueError(f"{_INVALID_PREFIX}: {detail}")


def _utf8(value, label: str) -> bytes:
    if isinstance(value, str):
        try:
            return value.encode("utf-8")
        except UnicodeEncodeError:
            _invalid(f"{label} is not valid UTF-8")
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    _invalid(f"{label} must be str or bytes")


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


class TrackedJs(str):
    """A string that remembers where its current value came from.

    A root always covers the complete source text.  Untransformed slices keep
    a contiguous absolute range in that root.  ``replace`` is the only content
    transformation used by the SDK reader; because it may change the length of
    the value, it retains the source range but marks the result so later
    slices cannot claim a position that is no longer provable.
    """

    def __new__(cls, text: str):
        if not isinstance(text, str):
            raise TypeError("TrackedJs requires a str")
        instance = str.__new__(cls, text)
        object.__setattr__(instance, "_origin", object())
        object.__setattr__(instance, "_start", 0)
        object.__setattr__(instance, "_end", len(text))
        object.__setattr__(instance, "_transformed", False)
        object.__setattr__(instance, "_root", True)
        return instance

    @classmethod
    def _derived(cls, value: str, origin, start: int, end: int, transformed: bool):
        instance = str.__new__(cls, value)
        object.__setattr__(instance, "_origin", origin)
        object.__setattr__(instance, "_start", start)
        object.__setattr__(instance, "_end", end)
        object.__setattr__(instance, "_transformed", transformed)
        object.__setattr__(instance, "_root", False)
        return instance

    def __setattr__(self, name, value):
        raise AttributeError("TrackedJs is immutable")

    def __delattr__(self, name):
        raise AttributeError("TrackedJs is immutable")

    @property
    def start(self) -> int:
        return self._start

    @property
    def end(self) -> int:
        return self._end

    @property
    def origin(self):
        return self._origin

    def __getitem__(self, key):
        if not isinstance(key, slice):
            return str.__getitem__(self, key)
        step = 1 if key.step is None else key.step
        if step != 1 or self._transformed:
            return str.__getitem__(self, key)
        start, stop, _ = key.indices(len(self))
        value = str.__getitem__(self, key)
        absolute_start = self._start + start
        if start >= stop:
            return self._derived(value, self._origin, absolute_start, absolute_start, False)
        return self._derived(value, self._origin, absolute_start, self._start + stop, False)

    def replace(self, old, new, count=-1):
        value = str.replace(self, old, new, count)
        return self._derived(value, self._origin, self._start, self._end, True)


def encode_translation(text: str) -> str:
    """Encode a translation as fixed UTF-16 code-unit escapes for the SDK.

    The SDK writer escapes quote characters and newlines but deliberately does
    not escape backslashes.  Encoding every character as ``\\uXXXX`` therefore
    produces a wire payload that is safe for its existing replacement code.
    """
    if not isinstance(text, str):
        raise ValueError(f"encode_translation requires str, got {type(text).__name__}")
    pieces = []
    for index, character in enumerate(text):
        code = ord(character)
        if 0xD800 <= code <= 0xDFFF:
            raise ValueError(f"lone surrogate at character index {index}: U+{code:04X}")
        if code <= 0xFFFF:
            pieces.append(f"\\u{code:04x}")
        else:
            code -= 0x10000
            high = 0xD800 + (code >> 10)
            low = 0xDC00 + (code & 0x3FF)
            pieces.append(f"\\u{high:04x}\\u{low:04x}")
    return "".join(pieces)


def map_js_groups(source, relative_path, groups, changes, *, bom=0):
    """Map RPGMTL read groups back to exact source literal byte spans.

    ``source`` must be the untransformed :class:`TrackedJs` root handed to the
    real SDK reader.  Group items that carry the same origin are matched by
    their absolute character range; text equality is never used as a fallback.
    """
    if not isinstance(source, TrackedJs):
        _invalid("source must be a TrackedJs root")
    if (not getattr(source, "_root", False) or getattr(source, "_transformed", True)
            or source.start != 0 or source.end != len(source)):
        _invalid("source must be an untampered TrackedJs root")
    if not isinstance(relative_path, str):
        _invalid("relative_path must be a str")
    if type(bom) is not int or bom not in (0, 3):
        _invalid("bom must be exactly 0 or 3")
    if not isinstance(groups, list):
        _invalid("groups must be a list")
    if not isinstance(changes, list):
        _invalid("changes must be a list")

    try:
        source_bytes = source.encode("utf-8")
    except UnicodeEncodeError:
        _invalid("source is not valid UTF-8")

    prefix = [0] * (len(source) + 1)
    total = 0
    for index, character in enumerate(source):
        code = ord(character)
        if code < 0x80:
            width = 1
        elif code < 0x800:
            width = 2
        elif code < 0x10000:
            if 0xD800 <= code <= 0xDFFF:
                _invalid("source contains a lone surrogate")
            width = 3
        else:
            width = 4
        total += width
        prefix[index + 1] = total
    if total != len(source_bytes):
        _invalid("source byte index is inconsistent")

    file_bytes = (_BOM if bom else b"") + source_bytes
    normalized_changes = []
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            _invalid(f"changes[{index}] must be a dict")
        for key in ("start", "end", "source_literal", "text"):
            if key not in change:
                _invalid(f"changes[{index}] is missing {key}")
        start, end = change["start"], change["end"]
        if type(start) is not int or type(end) is not int or start < 0 or end < 0:
            _invalid(f"changes[{index}] start/end must be nonnegative ints")
        if start >= end:
            _invalid(f"changes[{index}] has an empty or reversed span")
        if start < bom or end > len(file_bytes):
            _invalid(f"changes[{index}] span is outside the source")
        text = change["text"]
        if not isinstance(text, str):
            _invalid(f"changes[{index}].text must be a str")
        source_literal = _utf8(change["source_literal"], f"changes[{index}].source_literal")
        if (len(source_literal) < 2 or source_literal[0] not in (0x22, 0x27)
                or source_literal[-1] != source_literal[0]):
            _invalid(f"changes[{index}].source_literal must have matching single or double quotes")
        if source_literal != file_bytes[start:end]:
            _invalid(f"changes[{index}].source_literal does not match its source span")
        normalized_changes.append({"start": start, "end": end, "text": text})

    ordered_changes = sorted(normalized_changes, key=lambda item: (item["start"], item["end"]))
    previous = None
    for change in ordered_changes:
        if previous is not None:
            if change["start"] == previous["start"] and change["end"] == previous["end"]:
                _invalid("duplicate requested literal span")
            if change["start"] < previous["end"]:
                _invalid("overlapping requested literal spans")
        previous = change

    strings = {}
    group_records = []
    occurrences = {}
    next_id = 1
    source_origin = source.origin
    for group_index, group in enumerate(groups):
        if not isinstance(group, list):
            _invalid(f"groups[{group_index}] must be a list")
        if not group:
            _invalid(f"groups[{group_index}] is missing its label")
        label = group[0]
        if not isinstance(label, str):
            _invalid(f"groups[{group_index}] label must be a str")
        if "::" in label:
            _invalid(f"groups[{group_index}] is a virtual plugins.js group")
        records = []
        for item_offset, item in enumerate(group[1:], start=1):
            if not isinstance(item, str):
                _invalid(f"groups[{group_index}][{item_offset}] must be a str")
            global_id = next_id
            next_id += 1
            strings[global_id] = [str(item), None, 1, 0]
            record = {
                "global_id": global_id,
                "local_tl": None,
                "modified": 0,
            }
            if isinstance(item, TrackedJs):
                if item.origin is not source_origin:
                    _invalid(f"groups[{group_index}][{item_offset}] has forged provenance")
                start, end = item.start, item.end
                if (type(start) is not int or type(end) is not int
                        or start < 1 or end < start or end >= len(source)):
                    _invalid(f"groups[{group_index}][{item_offset}] has an invalid original range")
                opening = str.__getitem__(source, start - 1)
                closing = str.__getitem__(source, end)
                if opening not in ("'", '"') or closing != opening:
                    # The SDK also enumerates regex/templates. Keep the exact
                    # row for its writer, with no translation or approved span.
                    # A requested span in these rows remains unproven below.
                    records.append(record)
                    continue
                if _is_escaped(source, start - 1) or _is_escaped(source, end):
                    _invalid(f"groups[{group_index}][{item_offset}] has escaped literal delimiters")
                literal_start = bom + prefix[start - 1]
                literal_end = bom + prefix[end + 1]
                if literal_start >= literal_end:
                    _invalid(f"groups[{group_index}][{item_offset}] has an invalid literal span")
                span = (literal_start, literal_end)
                if span in occurrences:
                    _invalid("duplicate tracked literal occurrence")
                occurrences[span] = {
                    "group_index": group_index,
                    "item_index": item_offset,
                    "global_id": global_id,
                    "record": record,
                }
            records.append(record)
        group_records.append((label, records))

    found = []
    for change in normalized_changes:
        span = (change["start"], change["end"])
        occurrence = occurrences.get(span)
        if occurrence is None:
            _invalid("requested literal span has no proven occurrence")
        record = occurrence["record"]
        record["local_tl"] = encode_translation(change["text"])
        record["modified"] = 1
        found.append({
            "start": span[0],
            "end": span[1],
            "group_index": occurrence["group_index"],
            "item_index": occurrence["item_index"],
            "global_id": occurrence["global_id"],
        })

    files = {relative_path: []}
    for label, records in group_records:
        files[relative_path].append(
            [label] + [[record["global_id"], record["local_tl"], 1, 0, record["modified"]]
                       for record in records]
        )
    return {
        "project_strings": {"strings": strings, "files": files},
        "found": found,
    }
