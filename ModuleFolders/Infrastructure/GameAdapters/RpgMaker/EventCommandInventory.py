"""Read-only inventory of RPG Maker MV/MZ event commands (contract v1).

This module inspects an already-loaded JSON document only.  It never reads or
writes files, calls a model, or changes its inputs.  Records retain the exact
raw command dictionaries so later consumers can make their own evidence-based
decisions; this module never infers that an unapproved field is safe to change.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping

__all__ = ['inventory_document']

#: Command codes that produce one inventory record.
_INVENTORY_CODES = frozenset({355, 356, 357, 655})

#: Basename of a map data file, for example ``Map007.json``.
_MAP_BASENAME = re.compile(r'\AMap[0-9]+\.json\Z')

_JSON_SUFFIX = '.json'


def inventory_document(relative_path, document, *, plugin_rules=(), check=None) -> list[dict]:
    """Inventory script and plugin commands found in known event containers.

    ``relative_path`` is only inspected for its basename, which selects the
    supported containers.  ``check`` is an optional cooperative callback that
    is invoked for every traversed command; exceptions it raises propagate.
    """

    if not isinstance(relative_path, str):
        return []

    rules = _normalized_rules(plugin_rules)
    records = []
    for commands, list_pointer, scene_id in _iter_containers(relative_path, document):
        index = 0
        total = len(commands)
        while index < total:
            _run_check(check)
            command = commands[index]
            code = _command_code(command)

            if code == 355:
                raw_commands = [command]
                raw_indexes = [index]
                next_index = index + 1
                # Engine semantics: the 355 line consumes every immediately
                # following 655 line as one script record.
                while next_index < total and _command_code(commands[next_index]) == 655:
                    _run_check(check)
                    raw_commands.append(commands[next_index])
                    raw_indexes.append(next_index)
                    next_index += 1
                records.append(_build_record(
                    relative_path, scene_id, list_pointer,
                    raw_commands, raw_indexes, 355, rules,
                ))
                index = next_index
                continue

            if code in _INVENTORY_CODES:
                records.append(_build_record(
                    relative_path, scene_id, list_pointer,
                    [command], [index], code, rules,
                ))
            index += 1

    return records


# ---------------------------------------------------------------------------
# recognized event containers
# ---------------------------------------------------------------------------

def _basename(relative_path: str) -> str:
    return relative_path.replace('\\', '/').rsplit('/', 1)[-1]


def _iter_containers(relative_path, document):
    basename = _basename(relative_path)
    if _MAP_BASENAME.match(basename):
        yield from _map_containers(basename[:-len(_JSON_SUFFIX)], document)
    elif basename == 'CommonEvents.json':
        yield from _common_event_containers(document)
    elif basename == 'Troops.json':
        yield from _troop_containers(document)


def _map_containers(stem, document):
    if not isinstance(document, Mapping):
        return
    events = document.get('events')
    if not isinstance(events, list):
        return
    for event_index, event in enumerate(events):
        if not isinstance(event, Mapping):
            continue
        pages = event.get('pages')
        if not isinstance(pages, list):
            continue
        event_id = event.get('id', event_index)
        for page_index, page in enumerate(pages):
            if not isinstance(page, Mapping):
                continue
            commands = page.get('list')
            if not isinstance(commands, list):
                continue
            yield (
                commands,
                f'/events/{event_index}/pages/{page_index}/list',
                f'{stem}:event:{event_id}:page:{page_index}',
            )


def _common_event_containers(document):
    if not isinstance(document, list):
        return
    for index, entry in enumerate(document):
        if not isinstance(entry, Mapping):
            continue
        commands = entry.get('list')
        if not isinstance(commands, list):
            continue
        event_id = entry.get('id', index)
        yield commands, f'/{index}/list', f'common_event:{event_id}'


def _troop_containers(document):
    if not isinstance(document, list):
        return
    for index, entry in enumerate(document):
        if not isinstance(entry, Mapping):
            continue
        pages = entry.get('pages')
        if not isinstance(pages, list):
            continue
        troop_id = entry.get('id', index)
        for page_index, page in enumerate(pages):
            if not isinstance(page, Mapping):
                continue
            commands = page.get('list')
            if not isinstance(commands, list):
                continue
            yield (
                commands,
                f'/{index}/pages/{page_index}/list',
                f'troop:{troop_id}:page:{page_index}',
            )


# ---------------------------------------------------------------------------
# inventory records
# ---------------------------------------------------------------------------

def _build_record(relative_path, scene_id, list_pointer, raw_commands, raw_indexes,
                  code, rules) -> dict:
    copied_commands = [copy.deepcopy(command) for command in raw_commands]
    plugin, command_name, arguments = _identity(code, raw_commands[0])

    approved_fields = []
    unreviewed_fields = []
    if code == 357 and isinstance(arguments, Mapping):
        approved_fields = _approved_fields(rules, plugin, command_name, arguments)
        approved = set(approved_fields)
        unreviewed_fields = _sorted_keys(set(arguments.keys()) - approved)

    return {
        'path': relative_path,
        'scene_id': scene_id,
        'pointer': f'{list_pointer}/{raw_indexes[0]}',
        'command_index': raw_indexes[0],
        'code': code,
        'command_count': len(raw_commands),
        'parameter_pointers': [
            f'{list_pointer}/{index}/parameters' for index in raw_indexes
        ],
        'raw_commands': copied_commands,
        'source_sha256': _source_hash(copied_commands),
        'plugin': plugin,
        'command': command_name,
        'approved_fields': approved_fields,
        'unreviewed_fields': unreviewed_fields,
        'writes_enabled': False,
    }


def _identity(code, command):
    """Return ``(plugin, command_name, arguments)`` for one leading command."""

    if code == 357:
        parameters = _parameters(command)
        plugin = _string_at(parameters, 0)
        command_name = _string_at(parameters, 1)
        arguments = parameters[3] if (
            len(parameters) > 3 and isinstance(parameters[3], Mapping)
        ) else None
        return plugin, command_name, arguments

    if code == 356:
        legacy = _string_at(_parameters(command), 0)
        tokens = legacy.split()
        return (tokens[0] if tokens else ''), '', None

    return '', '', None


def _parameters(command) -> list:
    if isinstance(command, Mapping):
        parameters = command.get('parameters')
        if isinstance(parameters, list):
            return parameters
    return []


def _string_at(parameters, position: int) -> str:
    if position < len(parameters) and isinstance(parameters[position], str):
        return parameters[position]
    return ''


# ---------------------------------------------------------------------------
# rules, hashing and small helpers
# ---------------------------------------------------------------------------

def _normalized_rules(plugin_rules) -> tuple:
    if plugin_rules is None:
        return ()
    try:
        candidates = tuple(plugin_rules)
    except TypeError:
        return ()
    return tuple(rule for rule in candidates if isinstance(rule, Mapping))


def _approved_fields(rules, plugin: str, command_name: str, arguments: Mapping) -> list:
    approved = set()
    for rule in rules:
        if rule.get('evidence_status') != 'verified':
            continue
        if rule.get('plugin') != plugin or rule.get('command') != command_name:
            continue
        fields = rule.get('fields')
        if not isinstance(fields, (list, tuple)):
            continue
        for field in fields:
            if not isinstance(field, str):
                continue
            value = arguments.get(field)
            if isinstance(value, str) and value.strip() != '':
                approved.add(field)
    return _sorted_keys(approved)


def _sorted_keys(values) -> list:
    try:
        return sorted(values)
    except TypeError:
        return sorted(values, key=lambda value: (type(value).__name__, repr(value)))


def _source_hash(raw_commands) -> str:
    payload = json.dumps(
        raw_commands,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _command_code(command):
    if not isinstance(command, Mapping):
        return None
    code = command.get('code')
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return code


def _run_check(check) -> None:
    if check is not None and callable(check):
        check()
