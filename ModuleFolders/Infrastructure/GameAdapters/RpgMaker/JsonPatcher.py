"""Byte level JSON patching for extracted occurrences (contract v1)."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping

from ModuleFolders.Domain.GameProject.Models import hash_text

__all__ = ['patch_json', 'compile_json_changes', 'resolve_pointer', 'semantic_differences']

_BOM = b'\xef\xbb\xbf'
_UTF16_BOMS = (b'\xff\xfe', b'\xfe\xff')
_DRIVE_PATTERN = re.compile(r'\A[A-Za-z]:')


def compile_json_changes(original,replacements) -> list:
    """Compile logical translations to checked whole-leaf writer values.

    Native and external memory writers share this conversion. In particular a
    display unit inside an event expression is written as a quoted JS literal,
    rather than handing its unquoted logical text to a third-party writer.
    """
    entries=_entries(replacements)
    _reject_conflicts(entries)
    text,_=_decode(_as_bytes(original));document=json.loads(text)
    result=[]
    for pointer,expected,new_text,relative,codec in entries:
        from .EventWriteGuard import check_event_target
        check_event_target(document,relative,_parse_pointer(pointer),codec)
        old=resolve_pointer(document,pointer)
        if not isinstance(old,str) or hash_text(old)!=expected:raise ValueError('old value hash mismatch: '+pointer)
        if old!=new_text:result.append({'pointer':pointer,'source_text':old,'text':new_text})
    return result


def patch_json(original, replacements) -> bytes:
    """Replace occurrence values inside ``original`` bytes.

    Compiled physical pointers must be unique and non overlapping, resolve to an existing string
    whose SHA256 still matches ``expected_value_hash``.  Unchanged input is
    returned byte for byte; otherwise the document is rewritten as compact
    UTF-8 (BOM preserved) after proving the semantic differences equal exactly
    the changed pointers. Approved fragments sharing a leaf are compiled once.
    """

    payload = _as_bytes(original)
    entries = _entries(replacements)
    if not entries:
        return payload
    _reject_conflicts(entries)

    text, encoding = _decode(payload)
    before = json.loads(text)
    document = copy.deepcopy(before)

    changed = []
    for pointer, expected_hash, new_text, relative, codec in entries:
        tokens = _parse_pointer(pointer)
        from .EventWriteGuard import check_event_target
        check_event_target(before, relative, tokens, codec)
        current = _resolve(document, tokens, pointer)
        if not isinstance(current, str):
            raise ValueError(f'replacement target is not a string: {pointer}')
        if hash_text(current) != expected_hash:
            raise ValueError(f'old value hash mismatch: {pointer}')
        if current == new_text:
            continue
        _assign(document, tokens, new_text, pointer)
        changed.append(pointer)

    if not changed:
        return payload

    dumped = json.dumps(document, ensure_ascii=False, separators=(',', ':')) + _trailing(text)
    output = dumped.encode(encoding)
    reparsed = json.loads(output.decode(encoding))
    differences = semantic_differences(before, reparsed)
    if differences != set(changed):
        raise ValueError(
            'patch produced unexpected semantic differences: '
            + ', '.join(sorted(differences))
        )
    return output


def resolve_pointer(document, pointer):
    """Resolve an RFC6901 pointer or raise :class:`ValueError`."""

    tokens = _parse_pointer(pointer)
    return _resolve(document, tokens, pointer)


def semantic_differences(first, second) -> set:
    """Return the pointers at which two JSON documents differ semantically."""

    differences: set[str] = set()
    _diff(first, second, '', differences)
    return differences


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _as_bytes(original) -> bytes:
    if isinstance(original, (bytes, bytearray, memoryview)):
        return bytes(original)
    raise ValueError(f'original must be bytes, got {type(original).__name__}')


def _entries(replacements):
    entries=[];groups={};script_groups={}
    for item in replacements:
        entry=_entry(item);occurrence=item[0]
        locator=occurrence['locator'] if isinstance(occurrence,Mapping) else occurrence.locator
        if locator.get('value_codec')=='event-js-span-v1':
            script_groups.setdefault((entry[3],entry[0]),[]).append((locator,entry[1],item[1]))
        elif locator.get('note_group'):
            groups.setdefault((entry[3],entry[0]),[]).append((locator,entry[1],item[1]))
        else:entries.append(entry)
    from ModuleFolders.Domain.GameProject.NoteTagText import encode_group
    for (relative,pointer),values in groups.items():
        entries.append((pointer,values[0][1],encode_group(relative,values),relative,None))
    for (relative,pointer),values in script_groups.items():
        from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import _patch_encoded_script
        raw=values[0][0]['raw_expression'];expected=hash_text(raw)
        if any(loc['raw_expression']!=raw or digest!=expected for loc,digest,_ in values):raise ValueError('EVENT_SCRIPT_SOURCE_CHANGED')
        edits=[({'script_span':loc['event_script_span'],'expected':loc['span_text']},text) for loc,_,text in values]
        entries.append((pointer,expected,_patch_encoded_script(raw,edits),relative,'event-js-span-v1'))
    return entries


def _entry(item) -> tuple:
    if not isinstance(item, tuple) or len(item) != 2:
        raise ValueError('replacements must be (occurrence, text) pairs')
    occurrence, new_text = item
    if not isinstance(new_text, str):
        raise ValueError('replacement text must be a string')
    if isinstance(occurrence, Mapping):
        locator = occurrence.get('locator')
        expected = occurrence.get('expected_value_hash')
        relative = occurrence.get('relative_path', '')
    else:
        locator = getattr(occurrence, 'locator', None)
        expected = getattr(occurrence, 'expected_value_hash', None)
        relative = getattr(occurrence, 'relative_path', '')
    if not isinstance(locator, Mapping):
        raise ValueError('occurrence locator must be a mapping')
    pointer = locator.get('pointer')
    if not isinstance(pointer, str):
        raise ValueError('occurrence locator needs a string pointer')
    if not isinstance(expected, str) or expected == '':
        raise ValueError(f'occurrence needs an expected_value_hash: {pointer}')
    codec=locator.get('value_codec')
    if ('event_script_span' in locator or 'span_text' in locator) and codec!='event-js-span-v1':
        raise ValueError('EVENT_SCRIPT_LOCATOR_INVALID')
    if 'note_tag' in locator or 'raw_note' in locator:
        from ModuleFolders.Domain.GameProject.NoteTagText import encode_value
        new_text=encode_value(relative,locator,expected.lower(),new_text)
    if codec is not None:
        if codec=='event-js-span-v1':
            from ModuleFolders.Domain.GameProject.EventScriptSpan import validate_locator
            raw,_,_=validate_locator(locator)
            if hash_text(raw)!=expected.lower():raise ValueError('EVENT_LITERAL_SOURCE_MISMATCH')
            if isinstance(relative,str) and relative:_check_relative(relative)
            return (pointer,expected.lower(),new_text,relative if isinstance(relative,str) else '',codec)
        from ModuleFolders.Domain.GameProject.EventLiteralCodec import CODEC_ID,LINE_CODEC_ID,encode_literal,encode_line_literal
        if codec not in (CODEC_ID,LINE_CODEC_ID):raise ValueError('UNSUPPORTED_VALUE_CODEC: '+str(codec))
        raw=locator.get('raw_expression')
        if not isinstance(raw,str) or hash_text(raw)!=expected.lower():raise ValueError('EVENT_LITERAL_SOURCE_MISMATCH')
        new_text=(encode_line_literal(new_text,original=raw) if codec==LINE_CODEC_ID else encode_literal(new_text,original=raw))
    if isinstance(relative, str) and relative != '':
        _check_relative(relative)
    return (pointer, expected.lower(), new_text, relative if isinstance(relative, str) else '', codec)


def _check_relative(relative: str) -> None:
    text = relative.replace('\\', '/')
    if text.startswith('/') or _DRIVE_PATTERN.match(text):
        raise ValueError(f'occurrence relative_path must be relative: {relative!r}')
    for segment in text.split('/'):
        if segment in ('', '.', '..'):
            raise ValueError(f'occurrence relative_path must not escape its root: {relative!r}')
        if ':' in segment:
            raise ValueError(f'occurrence relative_path must not contain a drive: {relative!r}')


def _reject_conflicts(entries) -> None:
    pointers = [entry[0] for entry in entries]
    if len(set(pointers)) != len(pointers):
        raise ValueError('duplicate pointers in replacements')
    parsed = [_parse_pointer(pointer) for pointer in pointers]
    for first_index, first in enumerate(parsed):
        for second_index in range(first_index + 1, len(parsed)):
            second = parsed[second_index]
            if _is_prefix(first, second) or _is_prefix(second, first):
                raise ValueError(
                    'overlapping pointers in replacements: '
                    f'{pointers[first_index]} / {pointers[second_index]}'
                )


def _is_prefix(first: tuple, second: tuple) -> bool:
    return len(first) <= len(second) and second[:len(first)] == first


def _parse_pointer(pointer) -> tuple:
    if not isinstance(pointer, str):
        raise ValueError('pointer must be a string')
    if pointer == '':
        return ()
    if not pointer.startswith('/'):
        raise ValueError(f'pointer must start with "/": {pointer!r}')
    tokens = []
    for raw in pointer.split('/')[1:]:
        if re.search(r'~(?![01])', raw):
            raise ValueError(f'invalid RFC6901 escape: {pointer!r}')
        token = raw.replace('~1', '/').replace('~0', '~')
        if token in ('.', '..'):
            raise ValueError(f'pointer has a traversal token: {pointer!r}')
        tokens.append(token)
    return tuple(tokens)


def _resolve(document, tokens: tuple, pointer: str):
    current = document
    for token in tokens:
        if isinstance(current, Mapping):
            if token not in current:
                raise ValueError(f'pointer does not resolve: {pointer!r}')
            current = current[token]
        elif isinstance(current, list):
            current = current[_index(token, len(current), pointer)]
        else:
            raise ValueError(f'pointer does not resolve: {pointer!r}')
    return current


def _assign(document, tokens: tuple, value: str, pointer: str) -> None:
    if not tokens:
        raise ValueError('cannot replace the document root')
    parent = _resolve(document, tokens[:-1], pointer)
    key = tokens[-1]
    if isinstance(parent, Mapping):
        if key not in parent:
            raise ValueError(f'pointer field is missing: {pointer!r}')
        parent[key] = value
    elif isinstance(parent, list):
        parent[_index(key, len(parent), pointer)] = value
    else:
        raise ValueError(f'pointer parent is not a container: {pointer!r}')


def _index(token: str, length: int, pointer: str) -> int:
    if not re.fullmatch(r'0|[1-9][0-9]*', token):
        raise ValueError(f'pointer does not resolve: {pointer!r}')
    index = int(token)
    if index >= length:
        raise ValueError(f'pointer does not resolve: {pointer!r}')
    return index


def _diff(first, second, pointer: str, differences: set) -> None:
    if isinstance(first, Mapping) and isinstance(second, Mapping):
        for key in first:
            child = f'{pointer}/{_escape(key)}'
            if key not in second:
                differences.add(child)
            else:
                _diff(first[key], second[key], child, differences)
        for key in second:
            if key not in first:
                differences.add(f'{pointer}/{_escape(key)}')
        return
    if isinstance(first, list) and isinstance(second, list):
        if len(first) != len(second):
            differences.add(pointer)
            return
        for index, (left, right) in enumerate(zip(first, second)):
            _diff(left, right, f'{pointer}/{index}', differences)
        return
    if not _same(first, second):
        differences.add(pointer)


def _same(first, second) -> bool:
    if isinstance(first, bool) or isinstance(second, bool):
        return first is second
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        return first == second
    return type(first) is type(second) and first == second


def _decode(payload: bytes):
    if payload.startswith(_BOM):
        return payload.decode('utf-8-sig'), 'utf-8-sig'
    if payload.startswith(_UTF16_BOMS):
        raise ValueError('unsupported JSON encoding: utf-16')
    return payload.decode('utf-8'), 'utf-8'


def _trailing(text: str) -> str:
    if text.endswith('\r\n'):
        return '\r\n'
    if text.endswith('\n'):
        return '\n'
    return ''


def _escape(token) -> str:
    return str(token).replace('~', '~0').replace('/', '~1')
