"""Pure RPG Maker MV/MZ event command helpers (contract v1).

No filesystem or game state is touched here: every helper reasons about a plain
event command list (``code``/``indent``/``parameters`` mappings) and returns the
text candidates the native adapter is allowed to extract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ['EventText', 'iter_event_texts', 'summarize_unsupported']

SPEAKER_CODE = 101
CHOICE_START = 102
CHOICE_BRANCH = 402
CHOICE_CANCEL = 403
CHOICE_END = 404

#: Default text parameter indexes for plain text commands.
_TEXT_PARAMETERS = {
    401: (0,),
    405: (0,),
    320: (1,),
    324: (1,),
    325: (1,),
}

_ROLES = {
    320: 'actor_name',
    324: 'actor_nickname',
    325: 'actor_profile',
}

#: Command codes whose parameters are never auto-extracted.
_SKIPPED = frozenset({108, 408, 657, 111, 355, 655, 356, 357})
_PLUGIN_CODES = frozenset({356, 357})
_SCRIPT_CODES = frozenset({355, 655})


@dataclass(frozen=True)
class EventText:
    """One extractable text value inside an event command list."""

    code: int
    pointer: str
    text: str
    role: str
    kind: str
    group: str = ''
    speaker: str = ''
    command_index: int = 0


def iter_event_texts(
    commands,
    pointer_prefix: str,
    *,
    speaker: str = '',
    command_text_fields=None,
    plugin_command_rules=(),
):
    """Return the ordered :class:`EventText` candidates of one command list.

    ``pointer_prefix`` is an already escaped RFC6901 pointer to the ``list``
    array itself, for example ``/events/1/pages/0/list``.  Linked choice
    occurrences share a non-empty ``group`` so the extractor can build a single
    unit for the 102 choice and its matching 402 branch texts.
    """

    if not isinstance(commands, (list, tuple)):
        return []
    overrides = _normalized_overrides(command_text_fields)
    results = []
    consumed = set()
    current_speaker = speaker if isinstance(speaker, str) else ''

    for index, command in enumerate(commands):
        if index in consumed:
            continue
        code = _code(command)
        if code is None:
            continue
        parameters = _parameters(command)

        if code == 357 and len(parameters) >= 4 and isinstance(parameters[3], Mapping):
            for rule in plugin_command_rules:
                if rule.get('evidence_status') != 'verified':
                    continue
                if parameters[:2] != [rule['plugin'], rule['command']]:
                    continue
                for field in rule['fields']:
                    text = _text(parameters[3].get(field))
                    if text is not None:
                        escaped = field.replace('~', '~0').replace('/', '~1')
                        results.append(EventText(code, f'{pointer_prefix}/{index}/parameters/3/{escaped}',
                            text, 'plugin_text', 'plugin_text', '', current_speaker, index))
            continue

        if code in overrides:
            for position in overrides[code]:
                text = _text(parameters[position]) if position < len(parameters) else None
                if text is not None:
                    results.append(_text_item(
                        code, index, position, text, 'command_text', 'command_text',
                        '', current_speaker, pointer_prefix,
                    ))
            continue

        if code == SPEAKER_CODE:
            name = _text(parameters[4]) if len(parameters) > 4 else None
            current_speaker = name or ''
            if name is not None:
                results.append(_text_item(
                    code, index, 4, name, 'speaker', 'speaker', '',
                    current_speaker, pointer_prefix,
                ))
            continue

        if code == CHOICE_START:
            choices = parameters[0] if parameters and isinstance(parameters[0], list) else []
            indent = _indent(command)
            branches = _scan_branches(commands, index + 1, indent)
            for choice_index, choice in enumerate(choices):
                text = _text(choice)
                if text is None:
                    continue
                pointer = f'{pointer_prefix}/{index}/parameters/0/{choice_index}'
                group = f'choice:{pointer}'
                results.append(EventText(
                    code, pointer, text, 'choice', 'choice', group,
                    current_speaker, index,
                ))
                for position, branch_text in branches.get(choice_index, ()):
                    consumed.add(position)
                    results.append(EventText(
                        CHOICE_BRANCH, f'{pointer_prefix}/{position}/parameters/1',
                        branch_text, 'choice_branch', 'choice', group,
                        current_speaker, position,
                    ))
            continue

        if code == CHOICE_BRANCH:
            # Orphan branch labels are editor metadata, never independent units.
            continue

        if code in _SKIPPED or code in (CHOICE_CANCEL, CHOICE_END):
            continue

        positions = _TEXT_PARAMETERS.get(code)
        if not positions:
            continue
        role = _ROLES.get(code, 'dialogue')
        for position in positions:
            text = _text(parameters[position]) if position < len(parameters) else None
            if text is not None:
                results.append(_text_item(
                    code, index, position, text, role, role, '',
                    current_speaker, pointer_prefix,
                ))

    return results


def summarize_unsupported(commands) -> dict:
    """Aggregate skipped script/plugin instructions into stable summary keys."""

    summary: dict[str, int] = {}
    if not isinstance(commands, (list, tuple)):
        return summary
    for command in commands:
        code = _code(command)
        if code in _PLUGIN_CODES:
            parameters = _parameters(command)
            name = parameters[0].strip() if parameters and isinstance(parameters[0], str) else ''
            key = f'plugin:{name}' if name else 'plugin:unknown'
            summary[key] = summary.get(key, 0) + 1
        elif code in _SCRIPT_CODES:
            summary['script'] = summary.get('script', 0) + 1
    return summary


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _text_item(code, index, position, text, role, kind, group, speaker, prefix):
    return EventText(
        code, f'{prefix}/{index}/parameters/{position}', text, role, kind,
        group, speaker, index,
    )


def _scan_branches(commands, start: int, indent: int) -> dict:
    """Collect 402 branch texts of one 102 block, ignoring nested choices."""

    branches: dict[int, list] = {}
    for position in range(start, len(commands)):
        command = commands[position]
        code = _code(command)
        level = _indent(command)
        if level < indent:
            break
        if level == indent and code in (CHOICE_START, CHOICE_END):
            break
        if code == CHOICE_BRANCH and level == indent:
            parameters = _parameters(command)
            if len(parameters) < 2:
                continue
            branch = parameters[0]
            if isinstance(branch, bool) or not isinstance(branch, int):
                continue
            text = _text(parameters[1])
            if text is not None:
                branches.setdefault(branch, []).append((position, text))
    return branches


def _normalized_overrides(fields) -> dict:
    from .EventWriteGuard import normalize_command_fields
    return normalize_command_fields(fields)


def _code(command):
    if not isinstance(command, Mapping):
        return None
    code = command.get('code')
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return code


def _parameters(command) -> list:
    parameters = command.get('parameters') if isinstance(command, Mapping) else None
    return parameters if isinstance(parameters, list) else []


def _indent(command) -> int:
    indent = command.get('indent') if isinstance(command, Mapping) else None
    if isinstance(indent, bool) or not isinstance(indent, int):
        return 0
    return indent


def _text(value):
    if isinstance(value, str) and value.strip() != '':
        return value
    return None
