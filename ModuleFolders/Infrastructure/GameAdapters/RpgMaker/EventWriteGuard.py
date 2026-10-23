"""Prevent plain string writers from changing executable event parameters."""

from collections.abc import Mapping
from pathlib import PurePosixPath
import re

_OPAQUE_CODES = frozenset({108, 408, 657, 111, 205, 355, 655, 356})
_OVERRIDE_BLOCKED = _OPAQUE_CODES | {122, 357}
_LITERAL_CODEC = 'event-js-json-string-v1'


def normalize_command_fields(fields):
    if fields is None:
        return {}
    if not isinstance(fields, Mapping):
        raise ValueError('profile command_text_fields must be a mapping')
    result = {}
    for raw_code, values in fields.items():
        if type(raw_code) is int:
            code = raw_code
        elif isinstance(raw_code, str) and re.fullmatch(r'0|[1-9][0-9]*', raw_code):
            code = int(raw_code)
        else:
            raise ValueError('INVALID_COMMAND_TEXT_FIELDS: command code')
        if code < 0:
            raise ValueError('INVALID_COMMAND_TEXT_FIELDS: command code')
        indexes = [values] if type(values) is int else values
        if not isinstance(indexes, (list, tuple)) or any(type(i) is not int or i < 0 for i in indexes):
            raise ValueError('INVALID_COMMAND_TEXT_FIELDS: parameter indexes')
        if indexes and code in _OVERRIDE_BLOCKED:
            raise ValueError('UNSAFE_EVENT_TEXT_OVERRIDE: ' + str(code))
        if code in result:
            raise ValueError('INVALID_COMMAND_TEXT_FIELDS: duplicate command code')
        result[code] = tuple(dict.fromkeys(indexes))
    return result


def check_event_target(document, relative_path, tokens, codec=None):
    """Check only engine-defined event lists, never arbitrary custom JSON.

    ``tokens`` are validated RFC6901 tokens from the caller's pointer parser.
    The expression codec is limited to one exact single-variable assignment.
    The line codec permits a single JSON-quoted string at parameters/0 of an
    explicitly profiled 355/655 line; its encoder preserves all surrounding
    program text. The span codec permits explicit static template nodes there,
    with AST validation by extraction and the shared writer. Display-versus-logic
    authorization belongs to the profile.
    """
    name = PurePosixPath(relative_path.replace('\\', '/')).name
    if re.fullmatch(r'Map[0-9]+\.json', name):
        prefix_length = 5
        valid = (len(tokens) >= 8 and tokens[0] == 'events' and tokens[2] == 'pages'
                 and tokens[4] == 'list')
        indexes = (1, 3, 5)
    elif name == 'CommonEvents.json':
        prefix_length = 2
        valid = len(tokens) >= 5 and tokens[1] == 'list'
        indexes = (0, 2)
    elif name == 'Troops.json':
        prefix_length = 4
        valid = len(tokens) >= 7 and tokens[1] == 'pages' and tokens[3] == 'list'
        indexes = (0, 2, 4)
    else:
        valid = False
        indexes = ()
    if valid:
        valid = all(re.fullmatch(r'0|[1-9][0-9]*', tokens[i]) for i in indexes)
    if not valid:
        if codec is not None:
            raise ValueError('EVENT_LITERAL_TARGET_INVALID')
        return
    command_tokens = tokens[:prefix_length + 1]
    if tokens[prefix_length + 1] != 'parameters':
        if codec is not None:
            raise ValueError('EVENT_LITERAL_TARGET_INVALID')
        return
    command = document
    try:
        for token in command_tokens:
            command = command[int(token)] if isinstance(command, list) else command[token]
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError('EVENT_WRITE_TARGET_INVALID') from None
    code = command.get('code') if isinstance(command, Mapping) else None
    if type(code) is not int:
        raise ValueError('EVENT_WRITE_TARGET_INVALID')
    tail = tokens[prefix_length + 2:]
    if codec is not None:
        values = command.get('parameters')
        if codec in ('event-js-line-string-v1','event-js-span-v1'):
            if code not in (355,655) or tail!=('0',) or not isinstance(values,list) or len(values)!=1:
                raise ValueError('EVENT_LITERAL_TARGET_INVALID')
            if codec=='event-js-line-string-v1':
                from ModuleFolders.Domain.GameProject.EventLiteralCodec import decode_line_literal
                decode_line_literal(values[0])
            elif not isinstance(values[0],str) or '\n' in values[0] or '\r' in values[0]:
                raise ValueError('EVENT_LITERAL_TARGET_INVALID')
            return
        if (codec != _LITERAL_CODEC or code != 122 or tail != ('4',)
                or not isinstance(values, list) or len(values) != 5
                or any(type(v) is not int for v in values[:4])
                or not 1 <= values[0] <= 999999 or values[:4] != [values[0], values[0], 0, 4]):
            raise ValueError('EVENT_LITERAL_TARGET_INVALID')
        return
    if code in _OPAQUE_CODES or code == 122:
        raise ValueError('UNSAFE_EVENT_STRING_TARGET: ' + str(code))
    if code == 357 and (len(tail) < 2 or tail[0] != '3'):
        raise ValueError('UNSAFE_EVENT_STRING_TARGET: 357 identity')
