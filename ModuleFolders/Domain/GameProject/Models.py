"""Validated, JSON-safe domain models for the RPG game project foundation.

Contract: docs/rpg/IMPLEMENTATION_CONTRACT.md (v1).  Pure Python 3.13 standard
library only: no filesystem, database, Qt or model-SDK imports live in this
module.  Every public model is a dataclass that exposes ``to_dict()`` and
``from_dict()``; ``to_dict()`` only ever emits JSON-native values and
``from_dict()`` rejects unknown keys and malformed values instead of silently
accepting arbitrary input.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
from typing import Any

__all__ = [
    'COMMIT_STATUSES',
    'ISSUE_SEVERITIES',
    'CommitResult',
    'Issue',
    'ModelValidationError',
    'Occurrence',
    'TranslationProposal',
    'TranslationUnit',
    'hash_text',
]

#: Allowed :class:`CommitResult` statuses.
COMMIT_STATUSES: tuple[str, ...] = (
    'accepted',
    'rejected',
    'conflict',
    'locked',
    'duplicate',
)

#: Allowed :class:`Issue` severities (normalized to lower case).
ISSUE_SEVERITIES: tuple[str, ...] = ('info', 'warning', 'error')

#: Severities that block an accepted translation in the store.
BLOCKING_SEVERITIES: tuple[str, ...] = ('error',)

_HASH_PATTERN = re.compile(r'\A[0-9a-fA-F]{64}\Z')
_DRIVE_PATTERN = re.compile(r'\A[A-Za-z]:')
_WINDOWS_RESERVED_NAMES = frozenset(
    ['CON', 'PRN', 'AUX', 'NUL']
    + [f'COM{index}' for index in range(1, 10)]
    + [f'LPT{index}' for index in range(1, 10)]
)
_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*') | frozenset(chr(code) for code in range(32))
_MAX_JSON_DEPTH = 32


class ModelValidationError(ValueError):
    """Raised when model input is malformed or not JSON-safe.

    A domain ``ValueError`` subtype so callers can catch ``ValueError`` while
    still being able to inspect :attr:`code`.
    """

    def __init__(self, message: str, code: str = 'invalid_model_input') -> None:
        self.code = str(code)
        super().__init__(str(message))


def hash_text(text: str) -> str:
    """Return the lower case SHA256 digest of ``text`` encoded as UTF-8."""

    if not isinstance(text, str):
        raise ModelValidationError(
            f'hash_text expects a string, got {type(text).__name__}', 'invalid_text'
        )
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# validation helpers (pure functions, no I/O)
# ---------------------------------------------------------------------------

def _require_mapping(value: Any, name: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ModelValidationError(f'{name} must be a mapping, got {type(value).__name__}')
    return value


def _require_text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ModelValidationError(f'{name} must be a string, got {type(value).__name__}')
    if not allow_empty and value == '':
        raise ModelValidationError(f'{name} must not be empty')
    return value


def _require_count(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelValidationError(f'{name} must be an integer, got {type(value).__name__}')
    if value < minimum:
        raise ModelValidationError(f'{name} must be >= {minimum}, got {value}')
    return value


def _require_hash(value: Any, name: str, *, allow_empty: bool = False) -> str:
    text = _require_text(value, name, allow_empty=allow_empty)
    if text == '' and allow_empty:
        return ''
    if not _HASH_PATTERN.match(text):
        raise ModelValidationError(f'{name} must be a 64 character hexadecimal SHA256 digest')
    return text.lower()


def _json_safe(value: Any, name: str, *, depth: int = 0) -> Any:
    """Return a deep, JSON-native copy of ``value`` or raise."""

    if depth > _MAX_JSON_DEPTH:
        raise ModelValidationError(f'{name} nests deeper than {_MAX_JSON_DEPTH} levels')
    if value is None or isinstance(value, bool) or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ModelValidationError(f'{name} contains a non finite number: {value!r}')
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ModelValidationError(
                    f'{name} keys must be strings, got {type(key).__name__}'
                )
            result[key] = _json_safe(item, name, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, name, depth=depth + 1) for item in value]
    raise ModelValidationError(
        f'{name} contains a value that is not JSON-safe: {type(value).__name__}'
    )


def _require_json_dict(value: Any, name: str) -> dict:
    mapping = _require_mapping(value, name)
    safe = _json_safe(mapping, name)
    if not isinstance(safe, dict):  # defensive: mappings normalize to dict
        raise ModelValidationError(f'{name} must be a mapping')
    return safe


def _require_sequence(value: Any, name: str) -> tuple:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Iterable):
        raise ModelValidationError(f'{name} must be a sequence, got {type(value).__name__}')
    return tuple(value)


def _validate_relative_path(value: Any, name: str) -> str:
    """Lexically validate a game-relative path (no filesystem access)."""

    text = _require_text(value, name)
    if text.startswith(('/', '\\')) or _DRIVE_PATTERN.match(text):
        raise ModelValidationError(f'{name} must be a relative path: {text!r}')
    for segment in text.replace('\\', '/').split('/'):
        if segment in ('', '.', '..'):
            raise ModelValidationError(
                f'{name} contains an empty or traversal segment: {text!r}'
            )
        if any(char in _WINDOWS_INVALID_CHARS for char in segment):
            raise ModelValidationError(
                f'{name} contains characters that are invalid in a relative path: {text!r}'
            )
        if segment != segment.rstrip(' .'):
            raise ModelValidationError(
                f'{name} contains a segment with a trailing dot or space: {text!r}'
            )
        if segment.split('.')[0].upper() in _WINDOWS_RESERVED_NAMES:
            raise ModelValidationError(
                f'{name} uses a reserved Windows device name: {text!r}'
            )
    return text


def _bound_mapping(cls: type, data: Any) -> Mapping:
    """Reject non mappings and unknown keys for ``cls.from_dict``."""

    mapping = _require_mapping(data, f'{cls.__name__}.from_dict')
    allowed = {item.name for item in fields(cls)}
    unknown = sorted(str(key) for key in mapping if key not in allowed)
    if unknown:
        raise ModelValidationError(
            f'{cls.__name__}.from_dict received unknown fields: {", ".join(unknown)}'
        )
    return mapping


def _required_field(mapping: Mapping, key: str, cls: type) -> Any:
    if key not in mapping:
        raise ModelValidationError(
            f'{cls.__name__}.from_dict is missing required field {key!r}'
        )
    return mapping[key]


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    """A single validation/translation issue attached to a unit or a job."""

    code: str
    severity: str
    message: str
    unit_id: str = ''
    path: str = ''
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.code = _require_text(self.code, 'Issue.code')
        severity = _require_text(self.severity, 'Issue.severity').lower()
        if severity not in ISSUE_SEVERITIES:
            raise ModelValidationError(
                f'Issue.severity must be one of {ISSUE_SEVERITIES}, got {self.severity!r}'
            )
        self.severity = severity
        self.message = _require_text(self.message, 'Issue.message', allow_empty=True)
        self.unit_id = _require_text(self.unit_id, 'Issue.unit_id', allow_empty=True)
        self.path = _require_text(self.path, 'Issue.path', allow_empty=True)
        self.details = _require_json_dict(self.details, 'Issue.details')

    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'severity': self.severity,
            'message': self.message,
            'unit_id': self.unit_id,
            'path': self.path,
            'details': _json_safe(self.details, 'Issue.details'),
        }

    @classmethod
    def from_dict(cls, data: Any) -> 'Issue':
        mapping = _bound_mapping(cls, data)
        return cls(
            code=_required_field(mapping, 'code', cls),
            severity=_required_field(mapping, 'severity', cls),
            message=_required_field(mapping, 'message', cls),
            unit_id=mapping.get('unit_id', ''),
            path=mapping.get('path', ''),
            details=mapping.get('details', {}),
        )


@dataclass
class Occurrence:
    """One physical location of a source value inside a captured game file."""

    occurrence_id: str
    relative_path: str
    locator: dict
    expected_value_hash: str
    adapter_id: str = 'rpgmaker-native'
    role: str = 'text'
    ordinal: int = 0

    def __post_init__(self) -> None:
        self.occurrence_id = _require_text(self.occurrence_id, 'Occurrence.occurrence_id')
        self.relative_path = _validate_relative_path(
            self.relative_path, 'Occurrence.relative_path'
        )
        self.locator = _require_json_dict(self.locator, 'Occurrence.locator')
        self.expected_value_hash = _require_hash(
            self.expected_value_hash, 'Occurrence.expected_value_hash'
        )
        self.adapter_id = _require_text(self.adapter_id, 'Occurrence.adapter_id')
        self.role = _require_text(self.role, 'Occurrence.role')
        self.ordinal = _require_count(self.ordinal, 'Occurrence.ordinal')

    def to_dict(self) -> dict:
        return {
            'occurrence_id': self.occurrence_id,
            'relative_path': self.relative_path,
            'locator': _json_safe(self.locator, 'Occurrence.locator'),
            'expected_value_hash': self.expected_value_hash,
            'adapter_id': self.adapter_id,
            'role': self.role,
            'ordinal': self.ordinal,
        }

    @classmethod
    def from_dict(cls, data: Any) -> 'Occurrence':
        mapping = _bound_mapping(cls, data)
        return cls(
            occurrence_id=_required_field(mapping, 'occurrence_id', cls),
            relative_path=_required_field(mapping, 'relative_path', cls),
            locator=_required_field(mapping, 'locator', cls),
            expected_value_hash=_required_field(mapping, 'expected_value_hash', cls),
            adapter_id=mapping.get('adapter_id', 'rpgmaker-native'),
            role=mapping.get('role', 'text'),
            ordinal=mapping.get('ordinal', 0),
        )


@dataclass
class TranslationUnit:
    """A logical, translatable source string with all of its occurrences."""

    unit_id: str
    kind: str
    source_text: str
    scene_id: str = ''
    context: dict = field(default_factory=dict)
    occurrences: tuple = ()
    token_policy_id: str = 'rpgmaker-v1'
    source_hash: str = ''

    def __post_init__(self) -> None:
        self.unit_id = _require_text(self.unit_id, 'TranslationUnit.unit_id')
        self.kind = _require_text(self.kind, 'TranslationUnit.kind')
        self.source_text = _require_text(
            self.source_text, 'TranslationUnit.source_text', allow_empty=True
        )
        self.scene_id = _require_text(self.scene_id, 'TranslationUnit.scene_id', allow_empty=True)
        self.context = _require_json_dict(self.context, 'TranslationUnit.context')
        occurrences: list[Occurrence] = []
        for index, item in enumerate(
            _require_sequence(self.occurrences, 'TranslationUnit.occurrences')
        ):
            if isinstance(item, Occurrence):
                occurrences.append(item)
            elif isinstance(item, Mapping):
                occurrences.append(Occurrence.from_dict(item))
            else:
                raise ModelValidationError(
                    'TranslationUnit.occurrences[{}] must be an Occurrence, got {}'.format(
                        index, type(item).__name__
                    )
                )
        self.occurrences = tuple(occurrences)
        self.token_policy_id = _require_text(
            self.token_policy_id, 'TranslationUnit.token_policy_id'
        )
        supplied = _require_hash(
            self.source_hash, 'TranslationUnit.source_hash', allow_empty=True
        )
        computed = hash_text(self.source_text)
        if supplied and supplied != computed:
            raise ModelValidationError(
                'TranslationUnit.source_hash does not match source_text'
            )
        self.source_hash = computed

    def to_dict(self) -> dict:
        return {
            'unit_id': self.unit_id,
            'kind': self.kind,
            'source_text': self.source_text,
            'scene_id': self.scene_id,
            'context': _json_safe(self.context, 'TranslationUnit.context'),
            'occurrences': [occurrence.to_dict() for occurrence in self.occurrences],
            'token_policy_id': self.token_policy_id,
            'source_hash': self.source_hash,
        }

    @classmethod
    def from_dict(cls, data: Any) -> 'TranslationUnit':
        mapping = _bound_mapping(cls, data)
        return cls(
            unit_id=_required_field(mapping, 'unit_id', cls),
            kind=_required_field(mapping, 'kind', cls),
            source_text=_required_field(mapping, 'source_text', cls),
            scene_id=mapping.get('scene_id', ''),
            context=mapping.get('context', {}),
            occurrences=mapping.get('occurrences', ()),
            token_policy_id=mapping.get('token_policy_id', 'rpgmaker-v1'),
            source_hash=mapping.get('source_hash', ''),
        )


@dataclass
class TranslationProposal:
    """A proposed translation for one unit, with the guards needed to accept it."""

    unit_id: str
    text: str
    expected_source_hash: str
    expected_revision: int = 0
    job_id: str = ''
    request_item_id: str = ''
    origin: str = 'manual'
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.unit_id = _require_text(self.unit_id, 'TranslationProposal.unit_id')
        self.text = _require_text(self.text, 'TranslationProposal.text', allow_empty=True)
        self.expected_source_hash = _require_hash(
            self.expected_source_hash, 'TranslationProposal.expected_source_hash'
        )
        self.expected_revision = _require_count(
            self.expected_revision, 'TranslationProposal.expected_revision'
        )
        self.job_id = _require_text(self.job_id, 'TranslationProposal.job_id', allow_empty=True)
        self.request_item_id = _require_text(
            self.request_item_id, 'TranslationProposal.request_item_id', allow_empty=True
        )
        self.origin = _require_text(self.origin, 'TranslationProposal.origin')
        self.metadata = _require_json_dict(self.metadata, 'TranslationProposal.metadata')

    def to_dict(self) -> dict:
        return {
            'unit_id': self.unit_id,
            'text': self.text,
            'expected_source_hash': self.expected_source_hash,
            'expected_revision': self.expected_revision,
            'job_id': self.job_id,
            'request_item_id': self.request_item_id,
            'origin': self.origin,
            'metadata': _json_safe(self.metadata, 'TranslationProposal.metadata'),
        }

    @classmethod
    def from_dict(cls, data: Any) -> 'TranslationProposal':
        mapping = _bound_mapping(cls, data)
        return cls(
            unit_id=_required_field(mapping, 'unit_id', cls),
            text=_required_field(mapping, 'text', cls),
            expected_source_hash=_required_field(mapping, 'expected_source_hash', cls),
            expected_revision=mapping.get('expected_revision', 0),
            job_id=mapping.get('job_id', ''),
            request_item_id=mapping.get('request_item_id', ''),
            origin=mapping.get('origin', 'manual'),
            metadata=mapping.get('metadata', {}),
        )


@dataclass
class CommitResult:
    """Outcome of :meth:`ProjectStore.commit`."""

    unit_id: str
    status: str
    revision: int = 0
    issues: tuple = ()

    def __post_init__(self) -> None:
        self.unit_id = _require_text(self.unit_id, 'CommitResult.unit_id')
        status = _require_text(self.status, 'CommitResult.status').lower()
        if status not in COMMIT_STATUSES:
            raise ModelValidationError(
                f'CommitResult.status must be one of {COMMIT_STATUSES}, got {self.status!r}'
            )
        self.status = status
        self.revision = _require_count(self.revision, 'CommitResult.revision')
        issues: list[Issue] = []
        for index, item in enumerate(_require_sequence(self.issues, 'CommitResult.issues')):
            if isinstance(item, Issue):
                issues.append(item)
            elif isinstance(item, Mapping):
                issues.append(Issue.from_dict(item))
            else:
                raise ModelValidationError(
                    'CommitResult.issues[{}] must be an Issue, got {}'.format(
                        index, type(item).__name__
                    )
                )
        self.issues = tuple(issues)

    def to_dict(self) -> dict:
        return {
            'unit_id': self.unit_id,
            'status': self.status,
            'revision': self.revision,
            'issues': [issue.to_dict() for issue in self.issues],
        }

    @classmethod
    def from_dict(cls, data: Any) -> 'CommitResult':
        mapping = _bound_mapping(cls, data)
        return cls(
            unit_id=_required_field(mapping, 'unit_id', cls),
            status=_required_field(mapping, 'status', cls),
            revision=mapping.get('revision', 0),
            issues=mapping.get('issues', ()),
        )
