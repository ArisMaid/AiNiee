"""Deterministic RPG control-code protection; no model output can repair code IDs."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import uuid

from .Models import Issue


_COMMAND = re.compile(r'[A-Za-z_]+')
_SINGLE = set('.!|><^{}$\\\x1b')
_DEFAULT = {'V', 'N', 'P', 'C', 'I', 'G', 'PX', 'PY', 'FS', 'FN', 'OC', 'OW'}
_PARAM_REQUIRED = {'V', 'N', 'P', 'C', 'I', 'PX', 'PY', 'FS', 'FN', 'OC', 'OW'}
_MARKER = re.compile(r'__RPG_[0-9a-f]{12}_T\d{5}__')
_TEMPLATE = re.compile(r'\{[A-Za-z0-9_]+\}|%(?:[1-9][0-9]*|(?:\d+\$)?[sd])')
# MPP_ChoiceEX removes/evaluates lowercase if(...) and en(...) with a lazy
# first-close-parenthesis regex. Preserve that exact expression as one token,
# including an optional legacy backslash, instead of exposing logic to a model.
_CHOICE_CONDITION = re.compile(r'\\?(?:if|en)\([^\r\n]+?\)')
# Audited display markers such as SNS [word] are protected only when a caller
# explicitly configures them; the shape is never inferred from source text.
_LITERAL = re.compile(r'\[[A-Za-z][A-Za-z0-9_]{0,63}\]')
_MAX_LITERALS = 64


def _literal_tuple(literal_tokens) -> tuple[str, ...]:
    if not isinstance(literal_tokens, (list, tuple)):
        raise ValueError('literal_tokens must be a list or tuple of markers')
    if len(literal_tokens) > _MAX_LITERALS:
        raise ValueError(f'literal_tokens accepts at most {_MAX_LITERALS} markers')
    validated = []
    seen = set()
    for item in literal_tokens:
        if not isinstance(item, str) or not _LITERAL.fullmatch(item):
            raise ValueError(
                'Literal token must be a unique ASCII bracket marker such as [word]: '
                f'{item!r}')
        if item in seen:
            raise ValueError(f'Duplicate literal token: {item!r}')
        seen.add(item)
        validated.append(item)
    return tuple(validated)


@dataclass(frozen=True)
class ControlToken:
    raw: str
    start: int
    end: int
    command: str


@dataclass(frozen=True)
class ProtectedText:
    original: str
    text: str
    markers: tuple[str, ...]
    tokens: tuple[ControlToken, ...]
    issues: tuple[Issue, ...]
    unit_id: str = ''
    literal_tokens: tuple[str, ...] = ()

    def restore(self, translated: str) -> tuple[str, tuple[Issue, ...]]:
        if not isinstance(translated, str):
            return '', (Issue('INVALID_TRANSLATION', 'error', 'Translation must be a string', self.unit_id),)
        issues = list(self.issues)
        found = tuple(_MARKER.findall(translated))
        if found != self.markers:
            issues.append(Issue('TOKEN_MISMATCH', 'error',
                'Protected tokens are missing, duplicated, changed or reordered', self.unit_id))
        # A model must never bypass protection by returning literal engine code.
        # Only the text left after every legitimate marker is removed is judged,
        # so a correctly restored token.raw is never reported.
        stripped = _MARKER.sub('', translated)
        if '\\' in stripped:
            issues.append(Issue('UNEXPECTED_CONTROL_CODE', 'error',
                'Model inserted an unprotected backslash sequence', self.unit_id))
        injected = next((x for x in self.literal_tokens if x in stripped), None)
        if injected is not None:
            issues.append(Issue('UNEXPECTED_CONTROL_CODE', 'error',
                f'Model inserted an unprotected literal token: {injected}', self.unit_id))
        if issues:
            return translated, tuple(issues)
        for marker, token in zip(self.markers, self.tokens, strict=True):
            translated = translated.replace(marker, token.raw)
        return translated, ()


class TokenPolicy:
    """v2 preserves complete token order, variables and choice conditions.

    Plugin names are explicitly supplied after source audit. Unknown controls
    remain visible diagnostics and cannot be silently dropped or guessed.
    Audited literal bracket markers such as [word] are protected only when an
    explicit literal_tokens list/tuple is given; nothing is inferred.
    """
    def __init__(self, custom_commands=(), policy_id='rpgmaker-v2', *, literal_tokens=()):
        self.policy_id = policy_id
        self.commands = _DEFAULT | {str(x).upper() for x in custom_commands}
        self.literal_tokens = _literal_tuple(literal_tokens)
        # Longest first so a longer audited marker can never be split.
        self._literal_scan = tuple(sorted(self.literal_tokens, key=len, reverse=True))

    def scan(self, text: str, unit_id='') -> tuple[tuple[ControlToken, ...], tuple[Issue, ...]]:
        if not isinstance(text, str):
            raise ValueError('Text must be a string')
        tokens = []
        issues = []
        i = 0
        while i < len(text):
            condition = _CHOICE_CONDITION.match(text,i)
            if condition:
                tokens.append(ControlToken(condition.group(),i,condition.end(),'choice_condition'))
                i=condition.end()
                continue
            template = _TEMPLATE.match(text, i)
            if template:
                tokens.append(ControlToken(template.group(), i, template.end(), 'template'))
                i = template.end()
                continue
            if text[i] == '[':
                for literal in self._literal_scan:
                    if text.startswith(literal, i):
                        end = i + len(literal)
                        tokens.append(ControlToken(literal, i, end, 'literal'))
                        i = end
                        break
                else:
                    i += 1
                continue
            # Current chapter sources also contain RPG Maker's actual ESC prefix.
            # Preserve its raw spelling: a consumer replaces ESC-NN specifically.
            if text[i] not in ('\\', '\x1b'):
                i += 1
                continue
            start = i
            i += 1
            if i == len(text):
                issues.append(Issue('UNKNOWN_CONTROL_CODE', 'error', 'Trailing control prefix', unit_id))
                tokens.append(ControlToken(text[start:i], start, i, ''))
                break
            if text[i] in _SINGLE:
                command = text[i]
                i += 1
            else:
                match = _COMMAND.match(text, i)
                if not match:
                    i += 1
                    command = text[start + 1:i]
                    issues.append(Issue('UNKNOWN_CONTROL_CODE', 'error',
                        f'Unknown control sequence: {text[start:i]}', unit_id))
                else:
                    command = match.group()
                    i = match.end()
                    if command.upper() not in self.commands:
                        issues.append(Issue('UNKNOWN_CONTROL_CODE', 'error',
                            f'Unknown control command: {command}', unit_id))
            has_parameter = i < len(text) and text[i] == '['
            if has_parameter:
                depth = 0
                closed = False
                while i < len(text):
                    char = text[i]
                    i += 1
                    if char == '[':
                        depth += 1
                    elif char == ']':
                        depth -= 1
                        if depth == 0:
                            closed = True
                            break
                    if char in '\r\n' or depth > 16:
                        break
                if not closed:
                    issues.append(Issue('MALFORMED_CONTROL_CODE', 'error',
                        'Unclosed control argument', unit_id))
            elif command.upper() in _PARAM_REQUIRED:
                issues.append(Issue('MALFORMED_CONTROL_CODE', 'error',
                    f'Missing control argument: {command}', unit_id))
            tokens.append(ControlToken(text[start:i], start, i, command))
        return tuple(tokens), tuple(issues)

    def protect(self, text: str, unit_id='') -> ProtectedText:
        tokens, issues = self.scan(text, unit_id)
        prefix = uuid.uuid4().hex[:12]
        while f'__RPG_{prefix}_' in text:
            prefix = uuid.uuid4().hex[:12]
        pieces = []
        markers = []
        start = 0
        for index, token in enumerate(tokens):
            marker = f'__RPG_{prefix}_T{index:05d}__'
            pieces.extend((text[start:token.start], marker))
            markers.append(marker)
            start = token.end
        pieces.append(text[start:])
        return ProtectedText(text, ''.join(pieces), tuple(markers), tokens, issues, unit_id,
            self.literal_tokens)

    def validate(self, source: str, translated: str, unit_id='') -> tuple[Issue, ...]:
        original, source_issues = self.scan(source, unit_id)
        target, target_issues = self.scan(translated, unit_id)
        issues = list(source_issues + target_issues)
        left = tuple(t.raw for t in original)
        right = tuple(t.raw for t in target)
        if left != right:
            detail = {'source': dict(Counter(left)), 'target': dict(Counter(right))}
            issues.append(Issue('TOKEN_MISMATCH', 'error',
                'Control sequence or order differs from source', unit_id, details=detail))
        if _MARKER.search(translated):
            issues.append(Issue('PLACEHOLDER_RESIDUE', 'error', 'Unrestored translation placeholder', unit_id))
        return tuple(issues)
