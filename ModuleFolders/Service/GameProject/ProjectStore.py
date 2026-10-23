"""Transactional SQLite project store for the RPG translation pipeline.

Implements the v1 foundation contract in docs/rpg/IMPLEMENTATION_CONTRACT.md and
the project format 2 contract in docs/rpg/FORMAT_V2_CONTRACT.md.

Design rules enforced by this module:

* SQLite with ``foreign_keys = ON``, WAL journal and a busy timeout.  Every
  connection is private to one :class:`ProjectStore` and all access is
  serialized by an ``RLock`` (``check_same_thread=False`` is therefore safe).
* Every mutation runs in a single ``BEGIN IMMEDIATE`` ... ``COMMIT``
  transaction: revision counters, accepted edits and proposal status are
  written together, or not at all.
* ``schema_version`` is 2.  Schema 1 stays readable; a legacy project is
  upgraded only when an advanced capability (audited literal tokens or display
  value constraints) is first required, and that upgrade writes a retained,
  consistent pre-upgrade SQLite backup inside the same transaction before any
  data mutation.  ``required_features`` is a monotonic, sorted union and the
  capability gate is re-verified after ``BEGIN IMMEDIATE`` on every write.
* All statements are parameterized.  Rows are never removed with SQL and
  nothing is removed from the filesystem by this module: disappeared units,
  stale translations and rejected proposals are flagged and retained for audit.
* Job state machine (documented transitions)::

      QUEUED  -> RUNNING | CANCELLED | FAILED
      RUNNING -> PAUSED | SUCCEEDED | COMPLETED | FAILED | CANCELLED
      PAUSED  -> RUNNING | SUCCEEDED | COMPLETED | FAILED | CANCELLED
      SUCCEEDED / COMPLETED / FAILED / CANCELLED      (terminal)

  ``SUCCEEDED`` and ``COMPLETED`` are equivalent spellings of the terminal
  success state; both are accepted so independently written callers agree.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ModuleFolders.Domain.GameProject.Models import (
    BLOCKING_SEVERITIES,
    COMMIT_STATUSES,
    CommitResult,
    Issue,
    Occurrence,
    TranslationProposal,
    TranslationUnit,
    hash_text,
)

__all__ = [
    'DISPLAY_VALUE_CONSTRAINTS_FEATURE',
    'JOB_RUN_STATES',
    'JOB_TERMINAL_STATES',
    'JOB_TRANSITIONS',
    'LITERAL_TOKENS_FEATURE',
    'ProjectStore',
    'REQUIRED_FEATURES_KEY',
    'SCHEMA_VERSION',
    'SUPPORTED_FEATURES',
    'StoreViolation',
    'UPGRADE_BACKUP_RELATIVE',
]

#: Database file name created inside a project root.
DB_FILENAME = 'project.sqlite3'
#: Schema version written by this module; required for every advanced feature.
SCHEMA_VERSION = 2
#: Oldest schema version that stays readable; upgraded only on advanced use.
LEGACY_SCHEMA_VERSION = 1
#: Metadata key that declares the required advanced capabilities.
REQUIRED_FEATURES_KEY = 'required_features'
#: Capability: audited literal bracket markers are protected as tokens.
LITERAL_TOKENS_FEATURE = 'literal_tokens_v1'
#: Capability: display values are guarded by value constraints.
DISPLAY_VALUE_CONSTRAINTS_FEATURE = 'display_value_constraints_v1'
FONT_ALIASES_FEATURE = 'font_aliases_v1'
#: Capability identifiers understood by this module, sorted.
from ModuleFolders.Domain.GameProject.Capabilities import SUPPORTED_FEATURES
#: Token policy id that marks a profile as literal aware.
LITERAL_TOKENS_POLICY_ID = 'rpgmaker-v3'
#: Project relative directory that retains pre-upgrade backups.
UPGRADE_BACKUP_RELATIVE = 'migrations/v1-to-v2'
#: Default target language handled by the store.
DEFAULT_TARGET_LANGUAGE = 'zh-CN'
#: SQLite busy timeout in milliseconds.
BUSY_TIMEOUT_MS = 5000
BUSY_TIMEOUT_SECONDS = BUSY_TIMEOUT_MS / 1000.0

#: Valid job run states.
JOB_RUN_STATES: tuple[str, ...] = (
    'QUEUED', 'RUNNING', 'PAUSED', 'SUCCEEDED', 'COMPLETED', 'FAILED', 'CANCELLED',
    'PAUSE_REQUESTED', 'CANCEL_REQUESTED', 'INTERRUPTED',
    'COMMITTING',
)
#: Terminal job run states (no outgoing transitions).
JOB_TERMINAL_STATES: tuple[str, ...] = ('SUCCEEDED', 'COMPLETED', 'FAILED', 'CANCELLED')
#: Non terminal job run states that may still be owned by a process.
_ACTIVE_JOB_STATES: tuple[str, ...] = (
    'RUNNING', 'PAUSE_REQUESTED', 'PAUSED', 'CANCEL_REQUESTED', 'COMMITTING',
)
#: Documented job transitions; ``COMPLETED`` is an alias of ``SUCCEEDED``.
JOB_TRANSITIONS: dict[str, tuple[str, ...]] = {
    'QUEUED': ('RUNNING', 'CANCELLED', 'FAILED'),
    'RUNNING': ('COMMITTING', 'PAUSE_REQUESTED', 'CANCEL_REQUESTED', 'INTERRUPTED', 'PAUSED', 'SUCCEEDED', 'COMPLETED', 'FAILED', 'CANCELLED'),
    'PAUSED': ('RUNNING', 'CANCEL_REQUESTED', 'INTERRUPTED', 'SUCCEEDED', 'COMPLETED', 'FAILED', 'CANCELLED'),
    'PAUSE_REQUESTED': ('PAUSED', 'CANCEL_REQUESTED', 'INTERRUPTED', 'FAILED', 'COMPLETED'),
    'CANCEL_REQUESTED': ('CANCELLED', 'INTERRUPTED', 'FAILED'),
    'INTERRUPTED': ('QUEUED',),
    'COMMITTING': ('COMPLETED', 'FAILED', 'INTERRUPTED'),
    'SUCCEEDED': (),
    'COMPLETED': (),
    'FAILED': (),
    'CANCELLED': (),
}

_FILE_RECORD_FIELDS = (
    'relative_path', 'sha256', 'size', 'encoding', 'captured_path', 'adapter_id',
)
_FILE_RECORD_REQUIRED = ('relative_path', 'sha256', 'size')
_JOB_COLUMNS = {
    'run_state': 'run_state',
    'stage': 'stage',
    'checkpoint': 'checkpoint',
    'error': 'error',
    'error_json': 'error_json',
    'result': 'result_json',
}
_BUILD_DIGEST_KEYS = ('input_digest', 'digest', 'source_digest', 'input_hash')
#: Per-connection page-cache budget in KiB, allocated by SQLite on demand.
_PAGE_CACHE_KIB = 32 * 1024
#: Sentinel that distinguishes a missing metadata row from a JSON ``null``.
_MISSING = object()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    relative_path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    encoding TEXT NOT NULL,
    captured_path TEXT NOT NULL DEFAULT '',
    adapter_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS units (
    unit_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source_text TEXT NOT NULL,
    scene_id TEXT NOT NULL DEFAULT '',
    context_json TEXT NOT NULL DEFAULT '{}',
    occurrences_json TEXT NOT NULL DEFAULT '[]',
    token_policy_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    obsolete INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS translations (
    unit_id TEXT NOT NULL,
    target_language TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 0,
    source_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'untranslated',
    manual_locked INTEGER NOT NULL DEFAULT 0,
    job_id TEXT NOT NULL DEFAULT '',
    request_item_id TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (unit_id, target_language),
    FOREIGN KEY (unit_id) REFERENCES units (unit_id)
);
CREATE TABLE IF NOT EXISTS proposals (
    proposal_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id TEXT NOT NULL,
    target_language TEXT NOT NULL,
    text TEXT NOT NULL,
    expected_source_hash TEXT NOT NULL,
    expected_revision INTEGER NOT NULL,
    job_id TEXT NOT NULL DEFAULT '',
    request_item_id TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (unit_id) REFERENCES units (unit_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_proposals_delivery
    ON proposals (job_id, request_item_id, target_language)
    WHERE job_id <> '' AND request_item_id <> '';
CREATE TABLE IF NOT EXISTS edits (
    edit_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id TEXT NOT NULL,
    target_language TEXT NOT NULL,
    text TEXT NOT NULL,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    proposal_seq INTEGER,
    job_id TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (unit_id) REFERENCES units (unit_id),
    FOREIGN KEY (proposal_seq) REFERENCES proposals (proposal_seq)
);
CREATE TABLE IF NOT EXISTS issues (
    issue_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    unit_id TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    job_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    run_state TEXT NOT NULL,
    stage TEXT NOT NULL,
    checkpoint INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    error_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS builds (
    build_id TEXT PRIMARY KEY,
    input_digest TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class StoreViolation(ValueError):
    """Raised when a store request is invalid or conflicts with stored data."""

    def __init__(self, code: str, message: str = '') -> None:
        self.code = str(code)
        super().__init__(str(message) or self.code)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _require_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise StoreViolation('invalid_text', f'{name} must be a string, got {type(value).__name__}')
    if not allow_empty and value == '':
        raise StoreViolation('invalid_text', f'{name} must not be empty')
    return value


def _require_count(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StoreViolation('invalid_number', f'{name} must be an integer, got {type(value).__name__}')
    if value < minimum:
        raise StoreViolation('invalid_number', f'{name} must be >= {minimum}')
    return value


def _require_digest(value: object, name: str) -> str:
    text = _require_text(value, name)
    if len(text) != 64 or any(character not in '0123456789abcdefABCDEF' for character in text):
        raise StoreViolation('invalid_digest', f'{name} must be a 64 character hexadecimal digest')
    return text.lower()


def _require_relative_text(value: object, name: str) -> str:
    text = _require_text(value, name)
    if '\x00' in text:
        raise StoreViolation('invalid_path', f'{name} must not contain NUL')
    if text.startswith(('/', '\\')) or (len(text) > 1 and text[1] == ':'):
        raise StoreViolation('invalid_path', f'{name} must be a relative path')
    for segment in text.replace('\\', '/').split('/'):
        if segment in ('', '.', '..'):
            raise StoreViolation('invalid_path', f'{name} has an empty or traversal segment')
        if ':' in segment:
            raise StoreViolation('invalid_path', f'{name} must not contain alternate data streams')
    return text


def _ensure_json_value(value: object, name: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise StoreViolation('invalid_json_value', f'{name} is not JSON-safe: {error}') from error


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _normalize_metadata_value(value: object, name: str) -> object:
    """Return a JSON-safe metadata value; path objects become strings."""

    if isinstance(value, os.PathLike) and not isinstance(value, (str, bytes, bytearray)):
        path_text = os.fspath(value)
        if isinstance(path_text, bytes):
            raise StoreViolation('invalid_metadata', f'{name} must be a string path, not bytes')
        value = path_text
    _ensure_json_value(value, name)
    return value


def _coerce_path(value: object, name: str) -> Path:
    if isinstance(value, (bytes, bytearray)):
        raise StoreViolation('invalid_path', f'{name} must be a string path, not bytes')
    try:
        text = os.fspath(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise StoreViolation(
            'invalid_path', f'{name} must be a path-like value, got {type(value).__name__}'
        ) from error
    if isinstance(text, bytes) or text == '':
        raise StoreViolation('invalid_path', f'{name} must be a non empty string path')
    if '\x00' in text:
        raise StoreViolation('invalid_path', f'{name} must not contain NUL')
    return Path(os.path.abspath(text))


def _coerce_unit(value: object) -> TranslationUnit:
    if isinstance(value, TranslationUnit):
        return value
    if isinstance(value, Mapping):
        return TranslationUnit.from_dict(value)
    raise StoreViolation(
        'invalid_unit', f'expected a TranslationUnit, got {type(value).__name__}'
    )


def _coerce_proposal(value: object) -> TranslationProposal:
    if isinstance(value, TranslationProposal):
        return value
    if isinstance(value, Mapping):
        return TranslationProposal.from_dict(value)
    raise StoreViolation(
        'invalid_proposal', f'expected a TranslationProposal, got {type(value).__name__}'
    )


def _coerce_issue(value: object) -> Issue:
    if isinstance(value, Issue):
        return value
    if isinstance(value, Mapping):
        return Issue.from_dict(value)
    raise StoreViolation('invalid_issue', f'expected an Issue, got {type(value).__name__}')


def _coerce_issues(values: object) -> tuple[Issue, ...]:
    if isinstance(values, (Issue, Mapping)):
        raise StoreViolation('invalid_issues', 'issues must be an iterable of Issue')
    if not isinstance(values, Iterable):
        raise StoreViolation('invalid_issues', 'issues must be an iterable of Issue')
    return tuple(_coerce_issue(value) for value in values)


def _coerce_file_record(record: object) -> dict:
    if isinstance(record, Mapping):
        data = {str(key): value for key, value in record.items()}
    else:
        missing = [name for name in _FILE_RECORD_REQUIRED if not hasattr(record, name)]
        if missing:
            raise StoreViolation(
                'invalid_file_record',
                f'file record needs {", ".join(_FILE_RECORD_REQUIRED)}',
            )
        data = {name: getattr(record, name) for name in _FILE_RECORD_FIELDS if hasattr(record, name)}
    unknown = sorted(set(data) - set(_FILE_RECORD_FIELDS))
    if unknown:
        raise StoreViolation(
            'invalid_file_record', f'unknown file record fields: {", ".join(unknown)}'
        )
    missing = [name for name in _FILE_RECORD_REQUIRED if name not in data]
    if missing:
        raise StoreViolation(
            'invalid_file_record', f'file record needs {", ".join(missing)}'
        )
    return {
        'relative_path': _require_relative_text(data['relative_path'], 'file record relative_path'),
        'sha256': _require_digest(data['sha256'], 'file record sha256'),
        'size': _require_count(data['size'], 'file record size'),
        'encoding': _require_text(
            data.get('encoding', 'utf-8'), 'file record encoding', allow_empty=True
        ),
        'captured_path': _require_text(
            data.get('captured_path', ''), 'file record captured_path', allow_empty=True
        ),
        'adapter_id': _require_text(
            data.get('adapter_id', 'rpgmaker-native'), 'file record adapter_id'
        ),
    }


def _unit_payload(unit: TranslationUnit) -> dict:
    return {
        'kind': unit.kind,
        'source_text': unit.source_text,
        'scene_id': unit.scene_id,
        'context': unit.context,
        'occurrences': [occurrence.to_dict() for occurrence in unit.occurrences],
        'token_policy_id': unit.token_policy_id,
        'source_hash': unit.source_hash,
    }


def _unit_fingerprint(unit: TranslationUnit) -> str:
    return _canonical_json(_unit_payload(unit))


def _stored_unit_fingerprint(row: sqlite3.Row) -> str:
    return _canonical_json({
        'kind': row['kind'],
        'source_text': row['source_text'],
        'scene_id': row['scene_id'],
        'context': json.loads(row['context_json']),
        'occurrences': json.loads(row['occurrences_json']),
        'token_policy_id': row['token_policy_id'],
        'source_hash': row['source_hash'],
    })


#: Unit scalar columns compared directly against a prepared payload.
_PREPARED_UNIT_SCALAR_FIELDS = (
    'kind', 'source_text', 'scene_id', 'token_policy_id', 'source_hash',
)


def _prepare_unit_payload(unit: TranslationUnit) -> dict:
    """Encode a detached unit exactly once, before the write transaction.

    Every value is a scalar or a freshly encoded string, so caller mutations
    after this point cannot change what is persisted.
    """

    return {
        'unit_id': unit.unit_id,
        'kind': unit.kind,
        'source_text': unit.source_text,
        'scene_id': unit.scene_id,
        'context_json': _canonical_json(unit.context),
        'occurrences_json': _canonical_json(
            [occurrence.to_dict() for occurrence in unit.occurrences]
        ),
        'token_policy_id': unit.token_policy_id,
        'source_hash': unit.source_hash,
    }


def _stored_json_matches_prepared(stored: str, encoded: str, name: str) -> bool:
    """Compare a stored JSON column against its precomputed canonical encoding.

    Stored rows written by older code may use different formatting or key
    order, so those are parsed and compared by JSON value semantics.  A
    malformed column raises instead of silently comparing equal.
    """

    if stored == encoded:
        return True
    # Use the same canonical encoder as the previous fingerprint. Validate
    # the entire stored value even when a mismatching key/type could allow a
    # recursive equality check to skip a non-finite or malformed branch.
    return _canonical_json(_decode_json(stored, name)) == encoded


def _prepared_matches_stored_row(row: sqlite3.Row, payload: Mapping) -> bool:
    """Return whether an existing unit row equals a prepared payload."""

    scalars_match = True
    for field in _PREPARED_UNIT_SCALAR_FIELDS:
        stored = row[field]
        if not isinstance(stored, str):
            raise StoreViolation('corrupt_row', 'unit ' + field + ' is not stored as text')
        if stored != payload[field]:
            scalars_match = False
    # Both columns are checked eagerly, as the old fingerprint did, so a
    # malformed stored column is always reported instead of being overwritten
    # because some scalar happened to differ first.
    context_matches = _stored_json_matches_prepared(
        row['context_json'], payload['context_json'], 'unit context'
    )
    occurrences_match = _stored_json_matches_prepared(
        row['occurrences_json'], payload['occurrences_json'], 'unit occurrences'
    )
    return scalars_match and context_matches and occurrences_match


def _row_to_unit(row: sqlite3.Row) -> TranslationUnit:
    stored = _decode_json(row['occurrences_json'], 'unit occurrences')
    if not isinstance(stored, list):
        raise StoreViolation('corrupt_row', 'unit occurrences must be a JSON array')
    return TranslationUnit(
        unit_id=row['unit_id'],
        kind=row['kind'],
        source_text=row['source_text'],
        scene_id=row['scene_id'],
        context=_decode_json(row['context_json'], 'unit context'),
        occurrences=tuple(Occurrence.from_dict(item) for item in stored),
        token_policy_id=row['token_policy_id'],
        source_hash=row['source_hash'],
    )


def _decode_json(text: str, name: str) -> object:
    try:
        return json.loads(text)
    except (TypeError, ValueError) as error:
        raise StoreViolation('corrupt_row', f'{name} is not valid JSON') from error


def _read_metadata_value(connection: sqlite3.Connection, key: str, default: object) -> object:
    row = connection.execute('SELECT value FROM metadata WHERE key = ?', (key,)).fetchone()
    if row is None:
        return default
    return _decode_json(row['value'], f'metadata.{key}')


def _write_metadata_value(connection: sqlite3.Connection, key: str, value: object) -> None:
    connection.execute(
        'INSERT INTO metadata (key, value) VALUES (?, ?) '
        'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
        (key, _canonical_json(value)),
    )


def _validated_feature_list(value: object) -> list[str]:
    """Validate ``required_features``: unique, known, nonempty identifiers."""

    if not isinstance(value, (list, tuple)):
        raise StoreViolation(
            'invalid_required_features',
            'required_features must be a list of feature identifiers',
        )
    features: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or item == '':
            raise StoreViolation(
                'invalid_required_features',
                'required_features entries must be non empty strings',
            )
        if item not in SUPPORTED_FEATURES:
            raise StoreViolation('unsupported_feature', f'unknown required feature: {item}')
        if item in seen:
            raise StoreViolation(
                'invalid_required_features', f'duplicate required feature: {item}'
            )
        seen.add(item)
        features.append(item)
    return sorted(features)


def _read_schema_state(connection: sqlite3.Connection) -> tuple[int, list[str]]:
    """Return the validated ``(schema_version, required_features)`` pair."""

    try:
        version = _read_metadata_value(connection, 'schema_version', None)
        declared = _read_metadata_value(connection, REQUIRED_FEATURES_KEY, _MISSING)
    except sqlite3.Error as error:
        raise StoreViolation(
            'unsupported_schema', f'cannot read schema metadata: {error}'
        ) from error
    if type(version) is not int or version not in (LEGACY_SCHEMA_VERSION, SCHEMA_VERSION):
        raise StoreViolation(
            'unsupported_schema',
            f'expected schema_version {LEGACY_SCHEMA_VERSION} or {SCHEMA_VERSION}, '
            f'found {version!r}',
        )
    features = [] if declared is _MISSING else _validated_feature_list(declared)
    if features and version != SCHEMA_VERSION:
        raise StoreViolation(
            'unsupported_feature',
            f'schema_version {version} cannot declare required features: {features!r}',
        )
    return version, features


def _validated_literal_tokens(value: object, name: str) -> list[str]:
    """Validate a literal marker list exactly like :class:`TokenPolicy`."""

    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise StoreViolation(
            'invalid_literal_tokens', f'{name} must be a list of literal markers'
        )
    from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy
    try:
        TokenPolicy(literal_tokens=list(value))
    except ValueError as error:
        raise StoreViolation('invalid_literal_tokens', f'{name} is invalid: {error}') from error
    return list(value)


def _is_nonempty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes, bytearray, Mapping, list, tuple, set, frozenset)):
        return len(value) > 0
    return bool(value)


def _literal_aware(literal_tokens: object, policy_id: object) -> bool:
    """True when a nonempty literal list or the v3 policy needs the gate."""

    if _is_nonempty(literal_tokens):
        return True
    return isinstance(policy_id, str) and policy_id == LITERAL_TOKENS_POLICY_ID


def _required_features_for_profile(*, literal_tokens=None, policy_id=None, font_aliases=None, font_settings=None) -> set[str]:
    features={LITERAL_TOKENS_FEATURE} if _literal_aware(literal_tokens, policy_id) else set()
    if font_aliases or isinstance(font_settings,Mapping) and font_settings.get('aliases'):
        features.add(FONT_ALIASES_FEATURE)
    return features


def _validated_font_settings(value):
    if not isinstance(value,Mapping):raise StoreViolation('invalid_font_settings','font_settings must be a mapping')
    settings=dict(value)
    if 'aliases' in settings:
        from ModuleFolders.Domain.GameProject.FontPolicy import normalize_aliases
        settings['aliases']=normalize_aliases(settings['aliases'])
        if settings['aliases']:
            from .FontAliasRuntime import build_runtime
            build_runtime(settings['aliases'],settings.get('output_file'))
    return settings


def _required_features_for_units(units: Iterable) -> set[str]:
    """Infer capabilities from the incoming units themselves."""

    features: set[str] = set()
    for unit in units:
        if unit.token_policy_id == LITERAL_TOKENS_POLICY_ID:
            features.add(LITERAL_TOKENS_FEATURE)
        context = unit.context if isinstance(unit.context, Mapping) else {}
        if _is_nonempty(context.get('value_constraints')):
            features.add(DISPLAY_VALUE_CONSTRAINTS_FEATURE)
            if isinstance(context['value_constraints'],Mapping) and context['value_constraints'].get('preserve_newlines'):
                features.add('display_line_count_v1')
        for occurrence in unit.occurrences:
            if 'text_affixes' in occurrence.locator and 'source_span_id' not in occurrence.locator:
                raise StoreViolation('invalid_js_source_span','Text affixes require an approved source span')
            if 'source_span_id' in occurrence.locator:
                from ModuleFolders.Domain.GameProject.EncodedJsonText import script_span,source_span_body,text_affixes,AFFIX_FEATURE
                loc=occurrence.locator
                try:
                    script_span({**loc,'id':loc['source_span_id']})
                    parts=text_affixes(loc['text_affixes']) if 'text_affixes' in loc else None
                    body=source_span_body(loc.get('expected'),parts)
                except ValueError as error:raise StoreViolation('invalid_js_source_span',str(error)) from error
                if (occurrence.adapter_id!='js-literal' or any(k in loc for k in
                        ('static_text','scope_function','property_fields','literal_path','json_steps','script_span')) or
                        body!=unit.source_text or hash_text(body)!=unit.source_hash or
                        occurrence.expected_value_hash!=hash_text(loc['expected'])):
                    raise StoreViolation('invalid_js_source_span','Source spans require an unmixed matching JS string')
                features.add('js_source_spans_v1')
                if 'text_affixes' in loc:features.add(AFFIX_FEATURE)
            if any(k in occurrence.locator for k in ('literal_path','json_steps','json_hashes','json_types','script_span')):
                from ModuleFolders.Domain.GameProject.EncodedJsonText import literal_path,validate_spec,FEATURE
                if occurrence.adapter_id!='js-literal' or any(k in occurrence.locator for k in ('static_text','node_kind','scope_function','property_fields')):
                    raise StoreViolation('invalid_encoded_js_parameter','Encoded parameters need an exact JS literal path')
                literal_path(occurrence.locator.get('literal_path'))
                if 'json_steps' in occurrence.locator:validate_spec(occurrence.locator)
                elif any(k in occurrence.locator for k in ('json_hashes','json_types','script_span')):
                    raise StoreViolation('invalid_encoded_js_parameter','Missing JSON steps')
                features.add(FEATURE)
            if ('static_text' in occurrence.locator or 'node_kind' in occurrence.locator) and 'source_span_id' not in occurrence.locator:
                if (occurrence.adapter_id!='js-literal' or occurrence.locator.get('static_text') is not True or
                        not occurrence.locator.get('scope_function') or
                        occurrence.locator.get('node_kind') not in (None,'template-part')):
                    raise StoreViolation('invalid_js_display_fragment','Static JS text needs an explicit function scope')
                features.add('js_display_fragments_v1')
            codec=occurrence.locator.get('value_codec')
            if any(k in occurrence.locator for k in ('event_script_span','span_text')) and codec!='event-js-span-v1':
                raise StoreViolation('invalid_encoded_occurrence','Event script spans require their explicit codec')
            if 'note_tag' in occurrence.locator or 'raw_note' in occurrence.locator:
                from ModuleFolders.Domain.GameProject.NoteTagText import validate_locator,FEATURE
                decoded=validate_locator(occurrence.relative_path,occurrence.locator)
                if decoded!=unit.source_text or hash_text(occurrence.locator['raw_note'])!=occurrence.expected_value_hash:
                    raise StoreViolation('invalid_note_occurrence','Note value source/hash mismatch')
                features.add(FEATURE)
                if occurrence.locator.get('note_group'):
                    from ModuleFolders.Domain.GameProject.NoteTagText import GROUP_FEATURE
                    features.add(GROUP_FEATURE)
                if occurrence.locator.get('note_last_wins'):
                    from ModuleFolders.Domain.GameProject.NoteTagText import LAST_FEATURE
                    features.add(LAST_FEATURE)
            if codec is not None:
                from ModuleFolders.Domain.GameProject.EventLiteralCodec import CODEC_ID,LINE_CODEC_ID,decode_literal,decode_line_literal
                if codec not in (CODEC_ID,LINE_CODEC_ID,'event-js-span-v1'):raise StoreViolation('unsupported_value_codec',str(codec))
                raw=occurrence.locator.get('raw_expression')
                if codec=='event-js-span-v1':
                    from ModuleFolders.Domain.GameProject.EventScriptSpan import validate_locator,FEATURE
                    raw,_,decoded=validate_locator(occurrence.locator);features.add(FEATURE)
                else:decoded=decode_line_literal(raw) if codec==LINE_CODEC_ID else decode_literal(raw)
                if decoded!=unit.source_text or hash_text(raw)!=occurrence.expected_value_hash:
                    raise StoreViolation('invalid_encoded_occurrence','Event literal source/hash mismatch')
                if codec!='event-js-span-v1':features.add('event_js_line_v1' if codec==LINE_CODEC_ID else 'event_js_string_v1')
            if occurrence.locator.get('scope_function') or occurrence.locator.get('property_fields'):
                features.add('js_scoped_object_v1')
    return features


def _bump_content_revision(connection: sqlite3.Connection, now: str) -> int:
    current = _read_metadata_value(connection, 'content_revision', 0)
    if isinstance(current, bool) or not isinstance(current, int):
        raise StoreViolation('corrupt_metadata', 'content_revision must be an integer')
    value = current + 1
    _write_metadata_value(connection, 'content_revision', value)
    _write_metadata_value(connection, 'updated_at', now)
    return value


def _insert_issues(
    connection: sqlite3.Connection, issues: Iterable[Issue], job_id: str, now: str
) -> None:
    for issue in issues:
        connection.execute(
            'INSERT INTO issues (code, severity, message, unit_id, path, details_json, job_id, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                issue.code,
                issue.severity,
                issue.message,
                issue.unit_id,
                issue.path,
                _canonical_json(issue.details),
                job_id,
                now,
            ),
        )


def _insert_proposal(
    connection: sqlite3.Connection,
    proposal: TranslationProposal,
    target_language: str,
    status: str,
    revision: int,
    message: str,
    now: str,
) -> int:
    cursor = connection.execute(
        'INSERT INTO proposals (unit_id, target_language, text, expected_source_hash, '
        'expected_revision, job_id, request_item_id, origin, metadata_json, status, revision, '
        'message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            proposal.unit_id,
            target_language,
            proposal.text,
            proposal.expected_source_hash,
            proposal.expected_revision,
            proposal.job_id,
            proposal.request_item_id,
            proposal.origin,
            _canonical_json(proposal.metadata),
            status,
            revision,
            message,
            now,
        ),
    )
    return int(cursor.lastrowid or 0)


def _replay_delivery(
    connection: sqlite3.Connection,
    prior: sqlite3.Row,
    proposal: TranslationProposal,
    provided: tuple[Issue, ...],
    now: str,
) -> CommitResult:
    """Return the original outcome for a delivery key that was already used.

    The unique ``(job_id, request_item_id, target_language)`` index is never
    violated and the stored proposal is never rewritten, so redelivering the
    same request item is idempotent even when the first attempt was rejected,
    conflicted or blocked by a manual lock.
    """

    same_result = (
        prior['unit_id'] == proposal.unit_id
        and prior['text'] == proposal.text
        and prior['expected_source_hash'] == proposal.expected_source_hash
    )
    status = prior['status']
    revision = int(prior['revision'])
    if status == 'accepted' and same_result:
        return CommitResult(proposal.unit_id, 'duplicate', revision, ())
    if status != 'accepted' and same_result:
        replayed = status if status in COMMIT_STATUSES else 'rejected'
        return CommitResult(proposal.unit_id, replayed, revision, provided)
    generated = (
        Issue(
            'DUPLICATE_DELIVERY_MISMATCH',
            'error',
            'delivery key was already used for a different result',
            proposal.unit_id,
        ),
    )
    _insert_issues(connection, provided + generated, proposal.job_id, now)
    return CommitResult(proposal.unit_id, 'conflict', revision, provided + generated)


def _translation_dict(row: sqlite3.Row) -> dict:
    status = row['status']
    return {
        'unit_id': row['unit_id'],
        'target_language': row['target_language'],
        'text': row['text'],
        'revision': int(row['revision']),
        'source_hash': row['source_hash'],
        'status': status,
        'manual_locked': bool(row['manual_locked']),
        'job_id': row['job_id'],
        'request_item_id': row['request_item_id'],
        'origin': row['origin'],
        'updated_at': row['updated_at'],
        'stale': status == 'stale',
    }


def _job_dict(row: sqlite3.Row) -> dict:
    return {
        'job_id': row['job_id'],
        'operation': row['operation'],
        'payload': _decode_json(row['payload_json'], 'job payload'),
        'run_state': row['run_state'],
        'stage': row['stage'],
        'checkpoint': int(row['checkpoint']),
        'error': row['error'],
        'error_json': _decode_json(row['error_json'], 'job error_json'),
        'result': _decode_json(row['result_json'], 'job result'),
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }


def _build_dict(row: sqlite3.Row) -> dict:
    record = _decode_json(row['record_json'], 'build record')
    if not isinstance(record, dict):
        record = {'record': record}
    return {**record, 'input_digest': row['input_digest'], 'recorded_at': row['created_at']}


def _configure_connection(connection: sqlite3.Connection) -> None:
    try:
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute(f'PRAGMA busy_timeout = {int(BUSY_TIMEOUT_MS)}')
        journal = connection.execute('PRAGMA journal_mode = WAL').fetchone()
        connection.execute('PRAGMA synchronous = NORMAL')
        connection.execute(f'PRAGMA cache_size = -{_PAGE_CACHE_KIB}')
        enabled = connection.execute('PRAGMA foreign_keys').fetchone()
    except sqlite3.Error as error:
        raise StoreViolation('database_error', str(error)) from error
    if enabled is None or int(enabled[0]) != 1:
        raise StoreViolation('foreign_keys_unavailable', 'SQLite foreign key enforcement is off')
    if journal is None or str(journal[0]).lower() != 'wal':
        raise StoreViolation('wal_unavailable', f'SQLite WAL journal is unavailable: {journal!r}')


class ProjectStore:
    """SQLite backed, single-writer store for one RPG game project."""

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def __init__(self, root: object, *, readonly: bool = False) -> None:
        if type(readonly) is not bool:raise StoreViolation('invalid_readonly','readonly must be bool')
        self._readonly=readonly
        self._lock = threading.RLock()
        self._root = _coerce_path(root, 'root')
        from .PathGuard import safe_join
        self._db_path = safe_join(self._root,DB_FILENAME,must_exist=True)
        if readonly:
            for suffix in ('-wal','-journal'):
                sidecar=safe_join(self._root,DB_FILENAME+suffix)
                if sidecar.exists() and sidecar.stat().st_size:
                    raise StoreViolation('snapshot_not_frozen','Readonly snapshots require a complete database without a pending WAL or journal')
        if not self._root.is_dir():
            raise StoreViolation('project_missing', f'project directory does not exist: {self._root}')
        if not self._db_path.is_file():
            raise StoreViolation('project_missing', f'project database does not exist: {self._db_path}')
        self._closed = False
        try:
            self._connection = sqlite3.connect(
                self._db_path.as_uri()+'?mode=ro&immutable=1' if readonly else str(self._db_path),
                timeout=BUSY_TIMEOUT_SECONDS,
                isolation_level=None,
                check_same_thread=False,
                uri=readonly,
            )
        except sqlite3.Error as error:
            raise StoreViolation('database_error', str(error)) from error
        self._connection.row_factory = sqlite3.Row
        try:
            if readonly:
                self._connection.execute('PRAGMA query_only = ON')
                self._connection.execute('PRAGMA foreign_keys = ON')
                self._connection.execute(f'PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}')
            else:_configure_connection(self._connection)
            self._verify_schema()
        except BaseException:
            self._connection.close()
            self._closed = True
            raise

    @classmethod
    def create(cls, root: object, metadata: Mapping) -> 'ProjectStore':
        """Create a new project at ``root`` and return an open store."""

        root_path = _coerce_path(root, 'root')
        from .PathGuard import safe_join
        safe_join(root_path,DB_FILENAME)
        db_path = root_path / DB_FILENAME
        if root_path.exists():
            if not root_path.is_dir():
                raise StoreViolation('root_not_directory', f'root is not a directory: {root_path}')
            if os.path.lexists(db_path):
                raise StoreViolation('project_exists', f'project database already exists: {db_path}')
            if any(root_path.iterdir()):
                raise StoreViolation('root_not_empty', f'project root is not empty: {root_path}')
        else:
            try:
                root_path.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise StoreViolation('root_unavailable', f'cannot create {root_path}: {error}') from error
        initial = _validated_new_metadata(metadata)
        # Reserve the exact database path atomically; concurrent creators must
        # never initialize one another's database.
        from .PathGuard import safe_join
        db_path = safe_join(root_path, DB_FILENAME)
        with open(db_path, 'xb'):
            pass
        now = _utc_now()
        connection = None
        try:
            connection = sqlite3.connect(
                str(db_path),
                timeout=BUSY_TIMEOUT_SECONDS,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            _configure_connection(connection)
            connection.executescript(_SCHEMA)
            connection.execute('BEGIN IMMEDIATE')
            try:
                for key, value in initial.items():
                    _write_metadata_value(connection, key, value)
                _write_metadata_value(connection, 'created_at', now)
                _write_metadata_value(connection, 'updated_at', now)
                connection.execute('COMMIT')
            except BaseException:
                try:
                    connection.execute('ROLLBACK')
                except sqlite3.Error:
                    pass
                raise
        except sqlite3.Error as error:
            raise StoreViolation('database_error', str(error)) from error
        finally:
            if connection is not None:
                connection.close()
        return cls(root_path)

    def _verify_schema(self) -> None:
        """Validate schema version and required features.

        Called when a store is opened and again after ``BEGIN IMMEDIATE`` in
        every :meth:`_write` transaction, so a long-open connection can never
        write once another connection has declared an unsupported capability.
        """

        _read_schema_state(self._connection)

    def _require_open(self) -> None:
        if self._closed:
            raise StoreViolation('store_closed', 'the project store is closed')

    @property
    def root(self) -> Path:
        """Absolute path of the project root that owns ``project.sqlite3``."""

        return self._root

    def close(self) -> None:
        """Close the store.  Safe to call more than once."""

        with self._lock:
            if self._closed:
                return
            try:
                self._connection.close()
            finally:
                self._closed = True

    def __enter__(self) -> 'ProjectStore':
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._require_open()
            if self._readonly:raise StoreViolation('snapshot_readonly','Frozen input snapshots cannot be modified')
            try:
                self._connection.execute('BEGIN IMMEDIATE')
            except sqlite3.Error as error:
                raise StoreViolation('database_busy', str(error)) from error
            try:
                self._verify_schema()
                yield self._connection
            except sqlite3.IntegrityError as error:
                self._rollback_quietly()
                raise StoreViolation('integrity_error', str(error)) from error
            except sqlite3.Error as error:
                self._rollback_quietly()
                raise StoreViolation('database_error', str(error)) from error
            except BaseException:
                self._rollback_quietly()
                raise
            try:
                self._connection.execute('COMMIT')
            except sqlite3.Error as error:
                self._rollback_quietly()
                raise StoreViolation('commit_failed', str(error)) from error

    def _rollback_quietly(self) -> None:
        try:
            self._connection.execute('ROLLBACK')
        except sqlite3.Error:
            pass

    def _ensure_features(self, connection: sqlite3.Connection, features: Iterable) -> None:
        """Declare capability features, upgrading a legacy project if needed.

        Runs inside the caller's ``BEGIN IMMEDIATE`` transaction and before any
        data mutation.  A schema 1 project is upgraded exactly once: a
        consistent pre-upgrade snapshot is retained first, then
        ``required_features`` and ``schema_version`` are written.  A schema 2
        project only grows its feature set (sorted union, never removed).
        """

        wanted = {feature for feature in features}
        if not wanted:
            return
        version, current = _read_schema_state(connection)
        merged = sorted(set(current) | wanted)
        if version == SCHEMA_VERSION:
            if merged != current:
                # New capabilities can make a format-2 project unreadable to
                # an older application even without a physical SQL migration.
                self._write_pre_upgrade_backup('migrations/capabilities-v2')
                _write_metadata_value(connection, REQUIRED_FEATURES_KEY, merged)
            return
        # Legacy schema: the first advanced capability upgrades the project in
        # this very transaction.  The backup is written before the capability
        # metadata and before any unit, translation or config mutation.
        self._write_pre_upgrade_backup()
        _write_metadata_value(connection, REQUIRED_FEATURES_KEY, merged)
        _write_metadata_value(connection, 'schema_version', SCHEMA_VERSION)

    def _write_pre_upgrade_backup(self, backup_root=UPGRADE_BACKUP_RELATIVE) -> Path:
        """Retain a consistent pre-upgrade SQLite snapshot of the live database.

        The caller already holds the writer reservation, so no other writer can
        commit while this runs.  A separate read-only connection is used: the
        writer's own connection must never be used as a backup source while its
        transaction is open.  The destination is generated under a fresh UUID,
        checked with :func:`PathGuard.safe_join` and exclusively reserved with
        ``'xb'`` before SQLite writes a single page into it.
        """

        from .PathGuard import safe_join
        destination = safe_join(
            self._root, f'{backup_root}/{uuid.uuid4().hex}/{DB_FILENAME}'
        )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with open(destination, 'xb'):
                pass
        except OSError as error:
            raise StoreViolation(
                'upgrade_backup_failed',
                f'cannot reserve the pre-upgrade backup {destination}: {error}',
            ) from error
        source = None
        target = None
        try:
            source = sqlite3.connect(
                self._db_path.as_uri() + '?mode=ro',
                uri=True,
                timeout=BUSY_TIMEOUT_SECONDS,
                isolation_level=None,
            )
            target = sqlite3.connect(
                str(destination), timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None
            )
            source.backup(target)
            target.commit()
        except sqlite3.Error as error:
            raise StoreViolation(
                'upgrade_backup_failed',
                f'cannot back up the pre-upgrade project: {error}',
            ) from error
        finally:
            for connection in (target, source):
                if connection is not None:
                    try:
                        connection.close()
                    except sqlite3.Error:
                        pass
        return destination

    def _fetch_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            self._require_open()
            try:
                return self._connection.execute(sql, params).fetchall()
            except sqlite3.Error as error:
                raise StoreViolation('database_error', str(error)) from error

    def _fetch_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            self._require_open()
            try:
                return self._connection.execute(sql, params).fetchone()
            except sqlite3.Error as error:
                raise StoreViolation('database_error', str(error)) from error

    # ------------------------------------------------------------------
    # metadata
    # ------------------------------------------------------------------

    def metadata(self) -> dict:
        rows = self._fetch_all('SELECT key, value FROM metadata ORDER BY key')
        return {row['key']: _decode_json(row['value'], f'metadata.{row["key"]}') for row in rows}

    def update_metadata(self, changes: Mapping) -> dict:
        """Update metadata values inside one transaction.

        ``schema_version`` and ``required_features`` are immutable;
        ``dataset_revision`` and ``content_revision`` must be non negative
        integers when supplied.  The structural/profile edits bump dataset and
        content revisions.  Supplying ``token_literals`` or a
        ``rpgmaker-v3`` ``token_policy_id`` validates the literal grammar and
        declares (and if needed upgrades to) ``literal_tokens_v1`` before any
        value is written.
        """

        if not isinstance(changes, Mapping):
            raise StoreViolation('invalid_metadata', 'changes must be a mapping')
        if not changes:
            return self.metadata()
        prepared: dict[str, object] = {}
        for key, value in changes.items():
            if not isinstance(key, str) or key == '':
                raise StoreViolation('invalid_metadata', 'metadata keys must be non empty strings')
            if key in ('schema_version', REQUIRED_FEATURES_KEY,'profile_features','analysis_result'):
                raise StoreViolation('immutable_metadata', f'{key} cannot be changed')
            if key in ('dataset_revision', 'content_revision'):
                value = _require_count(value, f'metadata.{key}')
            if key in ('project_id', 'source_root', 'engine'):
                value = _require_text(value, f'metadata.{key}')
            if key == 'token_literals':
                value = _validated_literal_tokens(value, 'metadata.token_literals')
            if key == 'token_policy_id':
                value = _require_text(value, f'metadata.{key}')
            if key=='font_aliases':
                from ModuleFolders.Domain.GameProject.FontPolicy import normalize_aliases
                value=normalize_aliases(value)
            if key=='font_settings':value=_validated_font_settings(value)
            value = _normalize_metadata_value(value, f'metadata.{key}')
            prepared[key] = value
        required_features = _required_features_for_profile(
            literal_tokens=prepared.get('token_literals'),policy_id=prepared.get('token_policy_id'),
            font_aliases=prepared.get('font_aliases'),font_settings=prepared.get('font_settings'))
        now = _utc_now()
        with self._write() as connection:
            changed_keys = {key for key,value in prepared.items()
                if _read_metadata_value(connection,key,None) != value}
            if changed_keys & {'project_id', 'source_root', 'engine'}:
                raise StoreViolation('immutable_metadata', 'Project identity and source root are immutable')
            self._ensure_features(connection, required_features)
            for key, value in prepared.items():
                _write_metadata_value(connection, key, value)
            affecting = changed_keys & {'source_manifest_hash','profile_hash','token_commands','token_literals',
                'token_policy_id','target_language','font_aliases','font_settings','layout_settings','backend_routes','image_settings',
                'migration_lineage'}
            if affecting:
                _bump_content_revision(connection,now)
            if affecting & {'source_manifest_hash','profile_hash','token_commands','token_literals','token_policy_id'}:
                dataset = _read_metadata_value(connection,'dataset_revision',0)
                _write_metadata_value(connection,'dataset_revision',dataset+1)
            _write_metadata_value(connection, 'updated_at', now)
        return self.metadata()

    def analysis_record(self) -> dict:
        """A detached, versioned candidate record, including stale-source records."""
        meta=self.metadata()
        record=meta.get('analysis_result',{'revision':0,'dataset_revision':meta['dataset_revision'],
            'data':{},'job_id':'','origin':'empty'})
        if (not isinstance(record,dict) or type(record.get('revision')) is not int
                or record['revision']<0 or type(record.get('dataset_revision')) is not int
                or not isinstance(record.get('data'),dict)):
            raise StoreViolation('invalid_analysis_record','Canonical analysis record is malformed')
        return record

    def save_analysis_data(self,data: Mapping,*,project_id: str,expected_dataset_revision: int,
            expected_revision: int,job_id: str='') -> dict:
        """Compare and save candidates; model completion shares this transaction.

        This API never applies a candidate to accepted translations or global
        dictionaries. Explicit manual edits use the same analysis revision CAS.
        """
        identity=_require_text(project_id,'project_id')
        dataset=_require_count(expected_dataset_revision,'expected_dataset_revision')
        revision=_require_count(expected_revision,'expected_revision')
        job_id=_require_text(job_id,'job_id',allow_empty=True)
        if not isinstance(data,Mapping):raise StoreViolation('invalid_analysis_data','Analysis data must be an object')
        _ensure_json_value(data,'analysis_data')
        encoded=_canonical_json(data)
        prepared=_decode_json(encoded,'analysis_data')
        for field in ('characters','terms','non_translate'):
            if field in prepared and (not isinstance(prepared[field],list)
                    or any(not isinstance(row,dict) for row in prepared[field])):
                raise StoreViolation('invalid_analysis_data',f'{field} must contain objects')
        now=_utc_now()
        with self._write() as connection:
            if _read_metadata_value(connection,'project_id',None)!=identity:
                raise ValueError('ANALYSIS_PROJECT_CHANGED')
            if _read_metadata_value(connection,'dataset_revision',None)!=dataset:
                raise ValueError('DATASET_REVISION_CONFLICT')
            current=_read_metadata_value(connection,'analysis_result',{'revision':0,'data':{}})
            if not isinstance(current,dict) or type(current.get('revision')) is not int:
                raise StoreViolation('invalid_analysis_record','Canonical analysis revision is malformed')
            if job_id:
                row=connection.execute('SELECT * FROM jobs WHERE job_id=?',(job_id,)).fetchone()
                job=_job_dict(row) if row is not None else None
                payload=job['payload'] if job else {}
                if (job is None or job['operation']!='ANALYSIS'
                        or payload.get('project_id')!=identity or payload.get('request_mode')!='analysis'
                        or type(payload.get('dataset_revision')) is not int or payload['dataset_revision']!=dataset
                        or type(payload.get('analysis_revision')) is not int or payload['analysis_revision']!=revision):
                    raise ValueError('ANALYSIS_JOB_CONTEXT_INVALID')
                if (job['run_state']=='COMPLETED' and current.get('job_id')==job_id
                        and current['revision']==revision+1 and current.get('data')==prepared):
                    return current
                if job['run_state']!='COMMITTING':raise ValueError('ANALYSIS_JOB_NOT_COMMITTING')
            if current['revision']!=revision:raise ValueError('ANALYSIS_REVISION_CONFLICT')
            record={'revision':revision+1,'dataset_revision':dataset,'data':prepared,
                'job_id':job_id,'origin':'analysis' if job_id else 'manual','updated_at':now}
            self._ensure_features(connection,{'analysis_metadata_v1'})
            _write_metadata_value(connection,'analysis_result',record)
            _bump_content_revision(connection,now)
            if job_id:
                connection.execute("UPDATE jobs SET run_state='COMPLETED',stage='complete',updated_at=? WHERE job_id=?",(now,job_id))
        return record

    # ------------------------------------------------------------------
    # captured files
    # ------------------------------------------------------------------

    def put_files(self, records: Iterable) -> int:
        """Upsert explicitly supplied file records; no stored record is ever removed."""

        if isinstance(records, (str, bytes, Mapping)) or not isinstance(records, Iterable):
            raise StoreViolation('invalid_file_records', 'records must be an iterable of file records')
        prepared = [_coerce_file_record(record) for record in records]
        seen: set[str] = set()
        for record in prepared:
            if record['relative_path'] in seen:
                raise StoreViolation(
                    'duplicate_relative_path',
                    f'duplicate file record: {record["relative_path"]}',
                )
            seen.add(record['relative_path'])
        if not prepared:
            return 0
        now = _utc_now()
        with self._write() as connection:
            for record in prepared:
                connection.execute(
                    'INSERT INTO files (relative_path, sha256, size, encoding, captured_path, '
                    'adapter_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) '
                    'ON CONFLICT(relative_path) DO UPDATE SET sha256 = excluded.sha256, '
                    'size = excluded.size, encoding = excluded.encoding, '
                    'captured_path = excluded.captured_path, adapter_id = excluded.adapter_id, '
                    'updated_at = excluded.updated_at',
                    (
                        record['relative_path'],
                        record['sha256'],
                        record['size'],
                        record['encoding'],
                        record['captured_path'],
                        record['adapter_id'],
                        now,
                    ),
                )
        return len(prepared)

    def files(self) -> list[dict]:
        rows = self._fetch_all('SELECT * FROM files ORDER BY relative_path')
        return [
            {
                'relative_path': row['relative_path'],
                'sha256': row['sha256'],
                'size': int(row['size']),
                'encoding': row['encoding'],
                'captured_path': row['captured_path'],
                'adapter_id': row['adapter_id'],
                'updated_at': row['updated_at'],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # units
    # ------------------------------------------------------------------

    def replace_units(self, units: Iterable, *, image_settings: dict | None = None,
                      extraction_metadata: Mapping | None = None,
                      extraction_completion: Mapping | None = None,
                      extraction_issues: Iterable = ()) -> dict:
        """Insert or upsert units, flag disappeared units obsolete.

        Units are matched by ``unit_id``.  Supplied units are upserted; units
        that are missing from this call are marked obsolete and retained.  When
        the source hash of a unit changes its translation is
        marked ``stale`` with an incremented revision so the changed source can never
        reuse the old accepted text.  Dataset and content revisions are bumped
        once per call, and only when something actually changed.  A manual lock
        survives re-extraction; it is never cleared implicitly.
        """

        if isinstance(units, (TranslationUnit, Mapping, str, bytes)) or not isinstance(units, Iterable):
            raise StoreViolation('invalid_units', 'units must be an iterable of TranslationUnit')
        # Detach and revalidate every caller-owned model before any database
        # work: nested context/occurrence locators must not stay shared with
        # objects the caller may mutate while this call waits for the writer.
        prepared = [
            TranslationUnit.from_dict(_coerce_unit(unit).to_dict()) for unit in units
        ]
        final_issues=_coerce_issues(extraction_issues)
        completion=None
        if extraction_completion is not None:
            if (not isinstance(extraction_completion,Mapping) or
                    set(extraction_completion)!={'job_id','result','checkpoint'} or
                    not isinstance(extraction_completion['result'],Mapping)):
                raise StoreViolation('invalid_extraction_completion','Invalid extraction completion record')
            completion=dict(extraction_completion)
            completion['job_id']=_require_text(completion['job_id'],'extraction job_id')
            completion['checkpoint']=_require_count(completion['checkpoint'],'extraction checkpoint')
            _ensure_json_value(completion['result'],'extraction result')
            if not isinstance(extraction_metadata,Mapping) or extraction_metadata.get('extraction_complete') is not True:
                raise StoreViolation('invalid_extraction_completion','Completion requires a complete extraction dataset')
        elif final_issues:
            raise StoreViolation('invalid_extraction_completion','Atomic issues require an extraction completion record')
        extraction_changes={}
        if extraction_metadata is not None:
            allowed={'profile_id','profile_hash','profile_features','token_policy_id','token_commands','token_literals','font_aliases',
                'extraction_complete','extraction_stats','adapter_id','adapter_version'}
            if not isinstance(extraction_metadata,Mapping) or set(extraction_metadata)-allowed:
                raise StoreViolation('invalid_extraction_metadata','Unsupported extraction metadata fields')
            for key,value in extraction_metadata.items():
                value=_normalize_metadata_value(value,key)
                extraction_changes[key]=json.loads(_canonical_json(value))
            if 'profile_hash' in extraction_changes:_require_digest(extraction_changes['profile_hash'],'profile_hash')
            if 'profile_id' in extraction_changes:_require_text(extraction_changes['profile_id'],'profile_id',allow_empty=True)
            if 'token_policy_id' in extraction_changes:_require_text(extraction_changes['token_policy_id'],'token_policy_id')
            for key in ('adapter_id','adapter_version'):
                if key in extraction_changes:_require_text(extraction_changes[key],key)
            if 'extraction_complete' in extraction_changes and type(extraction_changes['extraction_complete']) is not bool:
                raise StoreViolation('invalid_extraction_metadata','extraction_complete must be bool')
            if 'extraction_stats' in extraction_changes and not isinstance(extraction_changes['extraction_stats'],dict):
                raise StoreViolation('invalid_extraction_metadata','extraction_stats must be a mapping')
            for key in ('token_commands','token_literals'):
                if key in extraction_changes and (not isinstance(extraction_changes[key],list) or
                        any(not isinstance(value,str) for value in extraction_changes[key])):
                    raise StoreViolation('invalid_extraction_metadata',key+' must be a string list')
            if 'token_literals' in extraction_changes:
                extraction_changes['token_literals'] = _validated_literal_tokens(
                    extraction_changes['token_literals'], 'extraction token_literals')
            if 'font_aliases' in extraction_changes:
                from ModuleFolders.Domain.GameProject.FontPolicy import normalize_aliases
                extraction_changes['font_aliases']=normalize_aliases(extraction_changes['font_aliases'])
            if 'profile_features' in extraction_changes:
                extraction_changes['profile_features']=_validated_feature_list(extraction_changes['profile_features'])
        required_features: set[str] = set()
        if extraction_changes:
            required_features |= _required_features_for_profile(
                literal_tokens=extraction_changes.get('token_literals'),
                policy_id=extraction_changes.get('token_policy_id'),
                font_aliases=extraction_changes.get('font_aliases'),
            )
        required_features |= _required_features_for_units(prepared)
        required_features |= set(extraction_changes.get('profile_features',[]))
        if image_settings is not None:
            if not isinstance(image_settings, dict):
                raise StoreViolation('invalid_image_settings', 'image settings must be a mapping')
            _ensure_json_value(image_settings, 'image_settings')
        incoming: set[str] = set()
        all_occurrence_ids = set()
        for unit in prepared:
            if unit.unit_id in incoming:
                raise StoreViolation('duplicate_unit_id', f'duplicate unit id: {unit.unit_id}')
            incoming.add(unit.unit_id)
            occurrence_ids: set[str] = set()
            for occurrence in unit.occurrences:
                if occurrence.occurrence_id in all_occurrence_ids:
                    raise StoreViolation('duplicate_occurrence_id', occurrence.occurrence_id)
                all_occurrence_ids.add(occurrence.occurrence_id)
                if occurrence.occurrence_id in occurrence_ids:
                    raise StoreViolation(
                        'duplicate_occurrence_id',
                        f'unit {unit.unit_id} repeats occurrence {occurrence.occurrence_id}',
                    )
                occurrence_ids.add(occurrence.occurrence_id)
        from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues
        ownership = ownership_issues(prepared)
        if ownership:
            issue = ownership[0]
            raise StoreViolation(issue.code.lower(), issue.code + ': ' + issue.path)
        # Canonical serialization happens once, outside the writer transaction.
        # No caller-owned unit is read again after this point.
        prepared_payloads = [_prepare_unit_payload(unit) for unit in prepared]
        # The encoded payloads own only immutable field values. Release the
        # duplicate model graph before taking the database writer lock.
        prepared.clear()
        summary = {
            'inserted': 0,
            'updated': 0,
            'obsolete': 0,
            'unchanged': 0,
            'dataset_revision': 0,
            'content_revision': 0,
        }
        now = _utc_now()
        # Bind containers are also prepared outside the writer transaction.
        # The new-row seq is filled from current SQLite state under the lock.
        prepared_rows = [(
            payload,
            [payload['unit_id'], 0, payload['kind'], payload['source_text'], payload['scene_id'],
             payload['context_json'], payload['occurrences_json'], payload['token_policy_id'],
             payload['source_hash'], now, now],
            [payload['kind'], payload['source_text'], payload['scene_id'], payload['context_json'],
             payload['occurrences_json'], payload['token_policy_id'], payload['source_hash'],
             now, payload['unit_id']],
        ) for payload in prepared_payloads]
        prepared_payloads.clear()
        with self._write() as connection:
            if completion is not None:
                job=connection.execute('SELECT operation,run_state FROM jobs WHERE job_id=?',
                    (completion['job_id'],)).fetchone()
                if job is None or job['operation']!='EXTRACT' or job['run_state']!='COMMITTING':
                    raise StoreViolation('invalid_extraction_completion','Extraction job must be COMMITTING')
            # Capability gate first: a legacy project is upgraded (with its
            # retained pre-upgrade backup) before any unit or metadata write.
            self._ensure_features(connection, required_features)
            existing_rows = connection.execute('SELECT * FROM units').fetchall()
            existing = {row['unit_id']: row for row in existing_rows}
            next_seq = 0
            for row in existing_rows:
                next_seq = max(next_seq, int(row['seq']))
            changed = False
            insert_sql = (
                'INSERT INTO units (unit_id, seq, kind, source_text, scene_id, context_json, '
                'occurrences_json, token_policy_id, source_hash, obsolete, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)'
            )
            pending_inserts: list[list] = []
            for payload, insert_values, update_values in prepared_rows:
                row = existing.get(payload['unit_id'])
                if row is None:
                    next_seq += 1
                    insert_values[1] = next_seq
                    pending_inserts.append(insert_values)
                    summary['inserted'] += 1
                    changed = True
                    continue
                if pending_inserts:
                    connection.executemany(insert_sql, pending_inserts)
                    pending_inserts.clear()
                if row['source_hash'] != payload['source_hash']:
                    connection.execute(
                        "UPDATE translations SET status = 'stale', revision = revision + 1, updated_at = ? "
                        "WHERE unit_id = ?",
                        (now, payload['unit_id']),
                    )
                    changed = True
                if int(row['obsolete']) or not _prepared_matches_stored_row(row, payload):
                    connection.execute(
                        'UPDATE units SET kind = ?, source_text = ?, scene_id = ?, context_json = ?, '
                        'occurrences_json = ?, token_policy_id = ?, source_hash = ?, obsolete = 0, '
                        'updated_at = ? WHERE unit_id = ?',
                        update_values,
                    )
                    summary['updated'] += 1
                    changed = True
                else:
                    summary['unchanged'] += 1
            if pending_inserts:
                connection.executemany(insert_sql, pending_inserts)
                pending_inserts.clear()
            for unit_id, row in existing.items():
                if unit_id in incoming or int(row['obsolete']):
                    continue
                connection.execute(
                    'UPDATE units SET obsolete = 1, updated_at = ? WHERE unit_id = ?',
                    (now, unit_id),
                )
                summary['obsolete'] += 1
                changed = True
            if image_settings is not None and _read_metadata_value(connection,'image_settings',{}) != image_settings:
                _write_metadata_value(connection,'image_settings',image_settings)
                changed = True
            for key,value in extraction_changes.items():
                if _read_metadata_value(connection,key,None)!=value:
                    _write_metadata_value(connection,key,value)
                    changed=True
            if changed:
                dataset = _read_metadata_value(connection, 'dataset_revision', 0)
                content = _read_metadata_value(connection, 'content_revision', 0)
                if isinstance(dataset, bool) or not isinstance(dataset, int):
                    raise StoreViolation('corrupt_metadata', 'dataset_revision must be an integer')
                if isinstance(content, bool) or not isinstance(content, int):
                    raise StoreViolation('corrupt_metadata', 'content_revision must be an integer')
                _write_metadata_value(connection, 'dataset_revision', dataset + 1)
                _write_metadata_value(connection, 'content_revision', content + 1)
                _write_metadata_value(connection, 'updated_at', now)
            summary['dataset_revision'] = _read_metadata_value(connection, 'dataset_revision', 0)
            summary['content_revision'] = _read_metadata_value(connection, 'content_revision', 0)
            if completion is not None:
                _insert_issues(connection,final_issues,completion['job_id'],now)
                result=dict(completion['result'],committed_dataset_revision=summary['dataset_revision'],
                    committed_content_revision=summary['content_revision'])
                connection.execute("UPDATE jobs SET run_state='COMPLETED',stage='complete',checkpoint=?,"
                    'result_json=?,updated_at=? WHERE job_id=?',
                    (completion['checkpoint'],_canonical_json(result),now,completion['job_id']))
        return summary

    def units(self, include_obsolete: bool = False) -> list[TranslationUnit]:
        """Return stored units in insertion order; obsolete ones are hidden by default."""

        sql = 'SELECT * FROM units'
        if not include_obsolete:
            sql += ' WHERE obsolete = 0'
        sql += ' ORDER BY seq'
        return [_row_to_unit(row) for row in self._fetch_all(sql)]

    def unit(self, unit_id: str) -> TranslationUnit | None:
        """Return one stored unit (obsolete included) or ``None`` when unknown."""

        text = _require_text(unit_id, 'unit_id')
        row = self._fetch_one('SELECT * FROM units WHERE unit_id = ?', (text,))
        return None if row is None else _row_to_unit(row)

    # ------------------------------------------------------------------
    # translations
    # ------------------------------------------------------------------

    def translation(self, unit_id: str, target_language: str = DEFAULT_TARGET_LANGUAGE) -> dict | None:
        """Return the stored translation row or ``None`` when there is none.

        ``status`` is ``translated``, ``untranslated`` or ``stale``; a stale row
        keeps its previous text for audit but must not be reused because its
        source changed (the boolean ``stale`` flag mirrors the status).
        """

        text = _require_text(unit_id, 'unit_id')
        language = _require_text(target_language, 'target_language')
        row = self._fetch_one(
            'SELECT * FROM translations WHERE unit_id = ? AND target_language = ?',
            (text, language),
        )
        return None if row is None else _translation_dict(row)

    def commit(
        self,
        proposal: object,
        issues: Iterable = (),
        target_language: str = DEFAULT_TARGET_LANGUAGE,
        *,
        manual_lock: bool | None = None,
    ) -> CommitResult:
        """Validate and accept a proposal inside one transaction.

        The accepted revision, the accepted edit (the checkpoint record in the
        ``edits`` table), the proposal status and the global ``content_revision``
        counter are all written in the same transaction.  Rejected, conflicting,
        locked and late proposals are stored in ``proposals`` and never modify
        the accepted text of a unit.

        ``manual_lock`` is reserved for an explicit owner/UI manual command.  It
        is validated exactly (``bool`` or ``None``) and may only accompany a
        proposal whose ``origin`` is ``manual``.  When supplied, the desired
        lock is part of the same writer transaction as the accepted text and an
        existing manual lock may be overridden by this command alone.  A
        metadata-only lock change keeps the text revision unchanged and is
        reported as ``accepted`` with the current revision; token/value checks
        apply to a changed text acceptance, not to that lock metadata command.
        Omitting the keyword keeps every pre-existing lock and commit rule
        untouched.
        """

        prepared = _coerce_proposal(proposal)
        if prepared.origin in ('reset-translate','reset-polish'):
            raise StoreViolation('reserved_origin','Task reset origins require the explicit reset_task_status command')
        language = _require_text(target_language, 'target_language')
        provided = _coerce_issues(issues)
        if manual_lock is not None:
            if type(manual_lock) is not bool:
                raise StoreViolation(
                    'invalid_manual_lock', 'manual_lock must be a boolean or None'
                )
            if prepared.origin != 'manual':
                raise StoreViolation(
                    'invalid_manual_lock',
                    'manual_lock is only valid for a proposal with origin "manual"',
                )
        explicit_manual = manual_lock is not None
        now = _utc_now()
        with self._write() as connection:
            prior = None
            if prepared.job_id and prepared.request_item_id:
                prior = connection.execute(
                    'SELECT * FROM proposals WHERE job_id = ? AND request_item_id = ? '
                    'AND target_language = ? ORDER BY proposal_seq LIMIT 1',
                    (prepared.job_id, prepared.request_item_id, language),
                ).fetchone()
            if prior is not None:
                return _replay_delivery(connection, prior, prepared, provided, now)
            unit_row = connection.execute(
                'SELECT * FROM units WHERE unit_id = ?', (prepared.unit_id,)
            ).fetchone()
            if unit_row is None:
                generated = (
                    Issue('UNKNOWN_UNIT', 'error', f'unknown unit: {prepared.unit_id}', prepared.unit_id),
                )
                _insert_issues(connection, provided + generated, prepared.job_id, now)
                return CommitResult(prepared.unit_id, 'rejected', 0, provided + generated)
            if int(unit_row['obsolete']):
                generated = (
                    Issue('OBSOLETE_UNIT', 'error', 'unit is obsolete in the current dataset', prepared.unit_id),
                )
                _insert_proposal(connection, prepared, language, 'rejected', 0, 'obsolete unit', now)
                _insert_issues(connection, provided + generated, prepared.job_id, now)
                return CommitResult(prepared.unit_id, 'rejected', 0, provided + generated)
            current_row = connection.execute(
                'SELECT * FROM translations WHERE unit_id = ? AND target_language = ?',
                (prepared.unit_id, language),
            ).fetchone()
            current_revision = int(current_row['revision']) if current_row is not None else 0
            # A batch can accept rows in separate transactions. A cooperative
            # project lock is not a substitute for checking the request epoch
            # in each writer transaction (direct Store callers can re-extract).
            # Standalone/manual delivery keys need not name a persisted job.
            if prepared.job_id and prepared.origin in ('translate','polish','model'):
                request=connection.execute('SELECT operation,payload_json,run_state FROM jobs WHERE job_id=?',
                    (prepared.job_id,)).fetchone()
                if request is not None and request['operation'] in ('TRANSLATE','POLISH'):
                    payload=_decode_json(request['payload_json'],'model job payload')
                    expected=payload.get('dataset_revision') if isinstance(payload,Mapping) else None
                    current_dataset=_read_metadata_value(connection,'dataset_revision',0)
                    code=None
                    if type(expected) is not int or expected<0:code='JOB_DATASET_INVALID'
                    elif type(current_dataset) is not int or current_dataset<0:code='PROJECT_DATASET_INVALID'
                    elif expected!=current_dataset:code='DATASET_REVISION_CONFLICT'
                    elif 'project_id' in payload and (not isinstance(payload['project_id'],str) or not payload['project_id']
                            or payload['project_id']!=_read_metadata_value(connection,'project_id','')):
                        code='PROJECT_IDENTITY_CONFLICT'
                    else:
                        targets=payload.get('unit_ids')
                        if (not isinstance(targets,list) or not targets
                                or any(not isinstance(value,str) or not value for value in targets)
                                or len(targets)!=len(set(targets))):code='JOB_REQUEST_ITEMS_INVALID'
                        elif prepared.unit_id not in targets or prepared.request_item_id!=prepared.unit_id:
                            code='REQUEST_ITEM_MISMATCH'
                        elif prepared.origin in ('translate','polish') and request['operation']!=prepared.origin.upper():
                            code='JOB_OPERATION_CONFLICT'
                        elif request['run_state']!='COMMITTING':code='JOB_STATE_CONFLICT'
                    if code:
                        generated=(Issue(code,'error','Model proposal does not match its current request context',prepared.unit_id),)
                        _insert_proposal(connection,prepared,language,'conflict',current_revision,code,now)
                        _insert_issues(connection,provided+generated,prepared.job_id,now)
                        return CommitResult(prepared.unit_id,'conflict',current_revision,provided+generated)
            if unit_row['source_hash'] != prepared.expected_source_hash:
                generated = (
                    Issue('SOURCE_HASH_MISMATCH', 'error', 'proposal targets changed source text', prepared.unit_id),
                )
                _insert_proposal(connection, prepared, language, 'conflict', current_revision, 'source hash mismatch', now)
                _insert_issues(connection, provided + generated, prepared.job_id, now)
                return CommitResult(prepared.unit_id, 'conflict', current_revision, provided + generated)
            if prepared.expected_revision != current_revision:
                generated = (
                    Issue(
                        'REVISION_CONFLICT',
                        'error',
                        f'expected revision {prepared.expected_revision}, current revision {current_revision}',
                        prepared.unit_id,
                    ),
                )
                _insert_proposal(connection, prepared, language, 'conflict', current_revision, 'revision conflict', now)
                _insert_issues(connection, provided + generated, prepared.job_id, now)
                return CommitResult(prepared.unit_id, 'conflict', current_revision, provided + generated)
            if (not explicit_manual and current_row is not None
                    and int(current_row['manual_locked'])):
                generated = (
                    Issue('MANUAL_LOCK', 'error', 'unit is manually locked', prepared.unit_id),
                )
                _insert_proposal(connection, prepared, language, 'locked', current_revision, 'manual lock', now)
                _insert_issues(connection, provided + generated, prepared.job_id, now)
                return CommitResult(prepared.unit_id, 'locked', current_revision, provided + generated)
            if explicit_manual:
                # Explicit owner/UI command. Identical text for a row whose
                # accepted source and status are current is metadata-only: no
                # new text revision, proposal or accepted edit.  A stale row is
                # deliberately excluded so identical text is revalidated and
                # re-accepted under a new revision.  The lock is applied in
                # this same transaction (the legacy placeholder insert keeps
                # the empty untranslated revision 0 row used by set_locked).
                no_row = current_row is None
                accepted_current = (
                    not no_row
                    and current_row['source_hash'] == unit_row['source_hash']
                    and current_row['status'] != 'stale'
                )
                if prepared.text == ('' if no_row else current_row['text']) and (
                        no_row or accepted_current):
                    if any(issue.severity in BLOCKING_SEVERITIES for issue in provided):
                        _insert_proposal(connection, prepared, language, 'rejected', current_revision,
                            'error issue', now)
                        _insert_issues(connection, provided, prepared.job_id, now)
                        return CommitResult(prepared.unit_id, 'rejected', current_revision, provided)
                    desired_lock = 1 if manual_lock else 0
                    if no_row:
                        if desired_lock:
                            connection.execute(
                                'INSERT INTO translations (unit_id, target_language, text, revision, '
                                'source_hash, status, manual_locked, job_id, request_item_id, origin, '
                                "updated_at) VALUES (?, ?, '', 0, ?, 'untranslated', 1, '', '', '', ?)",
                                (prepared.unit_id, language, unit_row['source_hash'], now),
                            )
                            _bump_content_revision(connection, now)
                        return CommitResult(prepared.unit_id, 'accepted', 0, provided)
                    if int(current_row['manual_locked']) != desired_lock:
                        connection.execute(
                            'UPDATE translations SET manual_locked = ?, updated_at = ? '
                            'WHERE unit_id = ? AND target_language = ?',
                            (desired_lock, now, prepared.unit_id, language),
                        )
                        _bump_content_revision(connection, now)
                    return CommitResult(
                        prepared.unit_id, 'accepted', current_revision, provided
                    )
            # Revalidate inside the writer transaction. A committer or external
            # adapter may have prepared its checks before a profile re-extract.
            # Source text alone does not identify the current token grammar.
            from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy
            from ModuleFolders.Domain.GameProject.ValueConstraints import validate_display_value
            unit=_row_to_unit(unit_row)
            policy=TokenPolicy(_read_metadata_value(connection,'token_commands',()),
                _read_metadata_value(connection,'token_policy_id','rpgmaker-v1'),
                literal_tokens=_read_metadata_value(connection,'token_literals',()))
            guarded=policy.validate(unit.source_text,prepared.text,unit.unit_id)+validate_display_value(
                unit.source_text,prepared.text,unit.context,unit.unit_id)
            provided+=tuple(issue for issue in guarded if issue not in provided)
            blocking = tuple(issue for issue in provided if issue.severity in BLOCKING_SEVERITIES)
            if blocking:
                _insert_proposal(connection, prepared, language, 'rejected', current_revision, 'error issue', now)
                _insert_issues(connection, provided, prepared.job_id, now)
                return CommitResult(prepared.unit_id, 'rejected', current_revision, provided)
            if prepared.text.strip() == '' and prepared.origin != 'manual':
                generated = (
                    Issue('EMPTY_TRANSLATION', 'error', 'empty text is only valid for manual edits', prepared.unit_id),
                )
                _insert_proposal(connection, prepared, language, 'rejected', current_revision, 'empty text', now)
                _insert_issues(connection, provided + generated, prepared.job_id, now)
                return CommitResult(prepared.unit_id, 'rejected', current_revision, provided + generated)
            new_revision = current_revision + 1
            status = 'translated' if prepared.text.strip() else 'untranslated'
            if current_row is None:
                if explicit_manual:
                    connection.execute(
                        'INSERT INTO translations (unit_id, target_language, text, revision, source_hash, '
                        'status, manual_locked, job_id, request_item_id, origin, updated_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (
                            prepared.unit_id,
                            language,
                            prepared.text,
                            new_revision,
                            unit_row['source_hash'],
                            status,
                            1 if manual_lock else 0,
                            prepared.job_id,
                            prepared.request_item_id,
                            prepared.origin,
                            now,
                        ),
                    )
                else:
                    connection.execute(
                        'INSERT INTO translations (unit_id, target_language, text, revision, source_hash, '
                        'status, manual_locked, job_id, request_item_id, origin, updated_at) '
                        'VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)',
                        (
                            prepared.unit_id,
                            language,
                            prepared.text,
                            new_revision,
                            unit_row['source_hash'],
                            status,
                            prepared.job_id,
                            prepared.request_item_id,
                            prepared.origin,
                            now,
                        ),
                    )
            elif explicit_manual:
                connection.execute(
                    'UPDATE translations SET text = ?, revision = ?, source_hash = ?, status = ?, '
                    'manual_locked = ?, job_id = ?, request_item_id = ?, origin = ?, updated_at = ? '
                    'WHERE unit_id = ? AND target_language = ?',
                    (
                        prepared.text,
                        new_revision,
                        unit_row['source_hash'],
                        status,
                        1 if manual_lock else 0,
                        prepared.job_id,
                        prepared.request_item_id,
                        prepared.origin,
                        now,
                        prepared.unit_id,
                        language,
                    ),
                )
            else:
                connection.execute(
                    'UPDATE translations SET text = ?, revision = ?, source_hash = ?, status = ?, '
                    'job_id = ?, request_item_id = ?, origin = ?, updated_at = ? '
                    'WHERE unit_id = ? AND target_language = ?',
                    (
                        prepared.text,
                        new_revision,
                        unit_row['source_hash'],
                        status,
                        prepared.job_id,
                        prepared.request_item_id,
                        prepared.origin,
                        now,
                        prepared.unit_id,
                        language,
                    ),
                )
            proposal_seq = _insert_proposal(
                connection, prepared, language, 'accepted', new_revision, '', now
            )
            connection.execute(
                'INSERT INTO edits (unit_id, target_language, text, revision, status, proposal_seq, '
                'job_id, origin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    prepared.unit_id,
                    language,
                    prepared.text,
                    new_revision,
                    status,
                    proposal_seq,
                    prepared.job_id,
                    prepared.origin,
                    now,
                ),
            )
            _insert_issues(connection, provided, prepared.job_id, now)
            _bump_content_revision(connection, now)
            return CommitResult(prepared.unit_id, 'accepted', new_revision, provided)

    def reset_task_status(self, mode, *, project_id, dataset_revision, expected_rows,
                          target_language=DEFAULT_TARGET_LANGUAGE) -> int:
        """Apply an explicit user reset as one audited scheduling transaction.

        Accepted text and locks stay intact. Each changed row receives a new
        revision and a reset operation origin; prior text provenance remains in
        edits/proposals. The new CAS revision rejects a pre-reset late response.
        All canonical eligibility, expected-source/revision, policy and audit
        checks share the writer transaction, including rollback on interruption.
        A reset never comes from normal model/import ``commit`` origins.
        """
        if mode not in ('translate','polish') or not isinstance(mode,str):
            raise StoreViolation('invalid_reset_mode','RESET_MODE_INVALID: translate or polish required')
        identity=_require_text(project_id,'project_id')
        dataset=_require_count(dataset_revision,'dataset_revision')
        language=_require_text(target_language,'target_language')
        if not isinstance(expected_rows,Mapping):
            raise StoreViolation('invalid_reset_projection','RESET_PROJECTION_INVALID')
        expected={}
        for unit_id,row in expected_rows.items():
            key=_require_text(unit_id,'unit_id')
            if not isinstance(row,Mapping) or set(row)!={'source_hash','revision'}:
                raise StoreViolation('invalid_reset_projection','RESET_PROJECTION_INVALID: '+key)
            expected[key]=(_require_text(row['source_hash'],'source_hash'),
                _require_count(row['revision'],'revision'))
        from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy
        from ModuleFolders.Domain.GameProject.ValueConstraints import validate_display_value
        from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues
        with self._write() as connection:
            if _read_metadata_value(connection,'project_id',None)!=identity:
                raise StoreViolation('project_conflict','RESET_PROJECT_CONFLICT')
            if _read_metadata_value(connection,'dataset_revision',0)!=dataset:
                raise StoreViolation('dataset_conflict','DATASET_REVISION_CONFLICT')
            units=[_row_to_unit(row) for row in connection.execute(
                'SELECT * FROM units WHERE obsolete=0 ORDER BY seq')]
            if {unit.unit_id for unit in units}!=set(expected):
                raise StoreViolation('incomplete_reset_projection','RESET_PROJECTION_INCOMPLETE: reload the project')
            ownership=ownership_issues(units)
            if ownership:raise StoreViolation(ownership[0].code.lower(),ownership[0].code)
            translations={row['unit_id']:row for row in connection.execute(
                'SELECT * FROM translations WHERE target_language=?',(language,))}
            policy=TokenPolicy(_read_metadata_value(connection,'token_commands',()),
                _read_metadata_value(connection,'token_policy_id','rpgmaker-v1'),
                literal_tokens=_read_metadata_value(connection,'token_literals',()))
            planned=[]
            for unit in units:
                source_hash,revision=expected[unit.unit_id]
                if source_hash!=unit.source_hash:
                    raise StoreViolation('source_conflict','SOURCE_HASH_MISMATCH: '+unit.unit_id)
                row=translations.get(unit.unit_id)
                if (row is None or row['manual_locked'] or row['status']=='stale'
                        or row['source_hash']!=unit.source_hash or not row['text'].strip()):continue
                if mode=='translate' and row['origin']=='reset-translate':continue
                if mode=='polish' and row['origin']!='polish':continue
                _,source_issues=policy.scan(unit.source_text,unit.unit_id)
                if source_issues:continue
                if int(row['revision'])!=revision:
                    raise StoreViolation('revision_conflict','REVISION_CONFLICT: reload '+unit.unit_id)
                issues=policy.validate(unit.source_text,row['text'],unit.unit_id)+validate_display_value(
                    unit.source_text,row['text'],unit.context,unit.unit_id)
                if any(issue.severity in BLOCKING_SEVERITIES for issue in issues):
                    raise StoreViolation('reset_validation_failed','RESET_VALIDATION_FAILED: '+unit.unit_id)
                proposal=TranslationProposal(unit.unit_id,row['text'],source_hash,revision,
                    origin='reset-'+mode,metadata={'operation':'user-task-reset','mode':mode,
                        'previous_origin':row['origin']})
                planned.append((proposal,row['status']))
            now=_utc_now()
            for proposal,status in planned:
                revision=proposal.expected_revision+1
                connection.execute(
                    'UPDATE translations SET revision=?, origin=?, job_id=?, request_item_id=?, updated_at=? '
                    'WHERE unit_id=? AND target_language=?',
                    (revision,proposal.origin,'','',now,proposal.unit_id,language))
                sequence=_insert_proposal(connection,proposal,language,'accepted',revision,'user task reset',now)
                connection.execute(
                    'INSERT INTO edits (unit_id,target_language,text,revision,status,proposal_seq,job_id,origin,created_at) '
                    'VALUES (?,?,?,?,?,?,?,?,?)',
                    (proposal.unit_id,language,proposal.text,revision,status,sequence,'',proposal.origin,now))
            if planned:_bump_content_revision(connection,now)
            return len(planned)

    def set_locked(self, unit_id: str, locked: bool, target_language: str = DEFAULT_TARGET_LANGUAGE) -> None:
        """Set the manual lock for a unit; the lock may precede any translation."""

        text = _require_text(unit_id, 'unit_id')
        language = _require_text(target_language, 'target_language')
        if not isinstance(locked, bool):
            raise StoreViolation('invalid_lock', 'locked must be a boolean')
        desired = 1 if locked else 0
        now = _utc_now()
        with self._write() as connection:
            unit_row = connection.execute(
                'SELECT * FROM units WHERE unit_id = ?', (text,)
            ).fetchone()
            if unit_row is None:
                raise StoreViolation('unknown_unit', f'unknown unit: {text}')
            row = connection.execute(
                'SELECT * FROM translations WHERE unit_id = ? AND target_language = ?',
                (text, language),
            ).fetchone()
            if row is None:
                if desired == 0:
                    return
                connection.execute(
                    'INSERT INTO translations (unit_id, target_language, text, revision, source_hash, '
                    'status, manual_locked, job_id, request_item_id, origin, updated_at) '
                    "VALUES (?, ?, '', 0, ?, 'untranslated', 1, '', '', '', ?)",
                    (text, language, unit_row['source_hash'], now),
                )
                _bump_content_revision(connection, now)
                return
            if int(row['manual_locked']) == desired:
                return
            connection.execute(
                'UPDATE translations SET manual_locked = ?, updated_at = ? '
                'WHERE unit_id = ? AND target_language = ?',
                (desired, now, text, language),
            )
            _bump_content_revision(connection, now)

    # ------------------------------------------------------------------
    # issues, proposals and edits
    # ------------------------------------------------------------------

    def put_issues(self, issues: Iterable, job_id: str = '') -> int:
        prepared = _coerce_issues(issues)
        job = _require_text(job_id, 'job_id', allow_empty=True)
        if not prepared:
            return 0
        with self._write() as connection:
            _insert_issues(connection, prepared, job, _utc_now())
        return len(prepared)

    def issues(self) -> list[dict]:
        rows = self._fetch_all('SELECT * FROM issues ORDER BY issue_seq')
        return [
            {
                'issue_id': int(row['issue_seq']),
                'code': row['code'],
                'severity': row['severity'],
                'message': row['message'],
                'unit_id': row['unit_id'],
                'path': row['path'],
                'details': _decode_json(row['details_json'], 'issue details'),
                'job_id': row['job_id'],
                'created_at': row['created_at'],
            }
            for row in rows
        ]

    def proposals(self) -> list[dict]:
        rows = self._fetch_all('SELECT * FROM proposals ORDER BY proposal_seq')
        return [
            {
                'proposal_id': int(row['proposal_seq']),
                'unit_id': row['unit_id'],
                'target_language': row['target_language'],
                'text': row['text'],
                'expected_source_hash': row['expected_source_hash'],
                'expected_revision': int(row['expected_revision']),
                'job_id': row['job_id'],
                'request_item_id': row['request_item_id'],
                'origin': row['origin'],
                'metadata': _decode_json(row['metadata_json'], 'proposal metadata'),
                'status': row['status'],
                'revision': int(row['revision']),
                'message': row['message'],
                'created_at': row['created_at'],
            }
            for row in rows
        ]

    def edits(self) -> list[dict]:
        rows = self._fetch_all('SELECT * FROM edits ORDER BY edit_seq')
        return [
            {
                'edit_id': int(row['edit_seq']),
                'unit_id': row['unit_id'],
                'target_language': row['target_language'],
                'text': row['text'],
                'revision': int(row['revision']),
                'status': row['status'],
                'proposal_id': None if row['proposal_seq'] is None else int(row['proposal_seq']),
                'job_id': row['job_id'],
                'origin': row['origin'],
                'created_at': row['created_at'],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------

    def create_job(self, operation: str, payload: Mapping | None = None) -> dict:
        op = _require_text(operation, 'operation')
        data = {} if payload is None else payload
        if not isinstance(data, Mapping):
            raise StoreViolation('invalid_payload', 'payload must be a mapping')
        _ensure_json_value(data, 'payload')
        job_id = uuid.uuid4().hex
        stage = 'queued'
        now = _utc_now()
        with self._write() as connection:
            connection.execute(
                'INSERT INTO jobs (job_id, operation, payload_json, run_state, stage, checkpoint, '
                "error, error_json, result_json, created_at, updated_at) "
                "VALUES (?, ?, ?, 'QUEUED', ?, 0, '', '{}', '{}', ?, ?)",
                (job_id, op, _canonical_json(data), stage, now, now),
            )
        return {
            'job_id': job_id,
            'operation': op,
            'payload': dict(data),
            'run_state': 'QUEUED',
            'stage': stage,
            'checkpoint': 0,
            'error': '',
            'error_json': {},
            'result': {},
            'created_at': now,
            'updated_at': now,
        }

    def update_job(self, job_id: str, **changes) -> dict:
        text = _require_text(job_id, 'job_id')
        unknown = sorted(set(changes) - set(_JOB_COLUMNS))
        if unknown:
            raise StoreViolation('invalid_job_change', f'unsupported job fields: {", ".join(unknown)}')
        now = _utc_now()
        with self._write() as connection:
            row = connection.execute('SELECT * FROM jobs WHERE job_id = ?', (text,)).fetchone()
            if row is None:
                raise StoreViolation('unknown_job', f'unknown job: {text}')
            updates: dict[str, object] = {}
            if 'run_state' in changes:
                state = _require_text(changes['run_state'], 'run_state').upper()
                if state not in JOB_RUN_STATES:
                    raise StoreViolation('invalid_run_state', f'unsupported run_state: {state}')
                current = row['run_state']
                if state != current and state not in JOB_TRANSITIONS.get(current, ()):
                    raise StoreViolation(
                        'invalid_transition', f'job transition {current} -> {state} is not allowed'
                    )
                updates['run_state'] = state
            if 'stage' in changes:
                updates['stage'] = _require_text(changes['stage'], 'stage')
            if 'checkpoint' in changes:
                updates['checkpoint'] = _require_count(changes['checkpoint'], 'checkpoint')
            if 'error' in changes:
                updates['error'] = _require_text(changes['error'], 'error', allow_empty=True)
            if 'error_json' in changes:
                detail = changes['error_json']
                if not isinstance(detail, Mapping):
                    raise StoreViolation('invalid_error_json', 'error_json must be a mapping')
                _ensure_json_value(detail, 'error_json')
                updates['error_json'] = _canonical_json(detail)
            if 'result' in changes:
                result = changes['result']
                if not isinstance(result, Mapping):
                    raise StoreViolation('invalid_result', 'result must be a mapping')
                _ensure_json_value(result, 'result')
                updates['result'] = _canonical_json(result)
            if updates:
                assignments = ', '.join(f'{_JOB_COLUMNS[name]} = ?' for name in updates)
                connection.execute(
                    f'UPDATE jobs SET {assignments}, updated_at = ? WHERE job_id = ?',
                    (*updates.values(), now, text),
                )
            refreshed = connection.execute('SELECT * FROM jobs WHERE job_id = ?', (text,)).fetchone()
            return _job_dict(refreshed)

    def jobs(self) -> list[dict]:
        rows = self._fetch_all('SELECT * FROM jobs ORDER BY created_at, job_id')
        return [_job_dict(row) for row in rows]

    def get_job(self, job_id: str) -> dict | None:
        """Read one task without decoding unrelated historical result blobs."""
        text = _require_text(job_id, 'job_id')
        row = self._fetch_one('SELECT * FROM jobs WHERE job_id = ?', (text,))
        return _job_dict(row) if row is not None else None

    def active_job_summaries(self, job_id: str | None = None) -> list[dict]:
        """Return compact summaries of jobs that may still be owned by a process.

        Only the five non terminal active states are selected and historical
        payload, error and result JSON is neither selected nor decoded.  An
        optional ``job_id`` narrows the read to exactly that one job.
        """

        placeholders = ', '.join('?' for _ in _ACTIVE_JOB_STATES)
        sql = (
            'SELECT job_id, operation, run_state, stage, checkpoint FROM jobs '
            f'WHERE run_state IN ({placeholders})'
        )
        params: tuple = _ACTIVE_JOB_STATES
        if job_id is not None:
            sql += ' AND job_id = ?'
            params += (_require_text(job_id, 'job_id'),)
        sql += ' ORDER BY created_at, job_id'
        return [
            {
                'job_id': row['job_id'],
                'operation': row['operation'],
                'run_state': row['run_state'],
                'stage': row['stage'],
                'checkpoint': int(row['checkpoint']),
            }
            for row in self._fetch_all(sql, params)
        ]

    def interrupt_job_if_active(self, job_id: str, *, error: str) -> bool:
        """Atomically mark one active job INTERRUPTED without touching its data.

        The conditional UPDATE runs inside the writer transaction, so a job
        whose owner finished after the caller enumerated it is left untouched
        and ``False`` is returned.  Only the run state, error and timestamp
        change; stage, checkpoint, payload, error_json and result are retained.
        """

        text = _require_text(job_id, 'job_id')
        message = _require_text(error, 'error')
        placeholders = ', '.join('?' for _ in _ACTIVE_JOB_STATES)
        now = _utc_now()
        with self._write() as connection:
            cursor = connection.execute(
                'UPDATE jobs SET run_state = ?, error = ?, updated_at = ? '
                f'WHERE job_id = ? AND run_state IN ({placeholders})',
                ('INTERRUPTED', message, now, text, *_ACTIVE_JOB_STATES),
            )
            return cursor.rowcount == 1

    def complete_migration_review(self, job_id, plan_id, expected_record, applied_record, result):
        """Publish the review registry and its completed attempt in one transaction."""
        job_id=_require_text(job_id,'migration job_id');plan_id=_require_text(plan_id,'migration plan_id')
        for value in (expected_record,applied_record,result):
            if not isinstance(value,Mapping):raise StoreViolation('invalid_migration_completion')
            _ensure_json_value(value,'migration completion')
        completed=result.get('accepted')
        if (expected_record.get('state')!='planned' or applied_record.get('state')!='applied'
                or result.get('plan_id')!=plan_id or result.get('passed') is not True
                or result.get('rejected')!=0 or type(completed) is not int or completed<0):
            raise StoreViolation('invalid_migration_completion')
        now=_utc_now()
        with self._write() as connection:
            row=connection.execute('SELECT * FROM jobs WHERE job_id=?',(job_id,)).fetchone()
            if (row is None or row['operation']!='MIGRATE' or row['run_state']!='COMMITTING'
                    or _decode_json(row['payload_json'],'migration payload').get('plan_id')!=plan_id):
                raise StoreViolation('invalid_migration_completion','Migration attempt is not committing this plan')
            registry=_read_metadata_value(connection,'migration_reviews',{})
            if not isinstance(registry,dict) or registry.get(plan_id)!=dict(expected_record):
                raise StoreViolation('migration_review_changed')
            registry[plan_id]=dict(applied_record)
            _write_metadata_value(connection,'migration_reviews',registry)
            _write_metadata_value(connection,'updated_at',now)
            connection.execute("UPDATE jobs SET run_state='COMPLETED',stage='complete',checkpoint=?,result_json=?,updated_at=? WHERE job_id=?",
                (completed,_canonical_json(result),now,job_id))
            return _job_dict(connection.execute('SELECT * FROM jobs WHERE job_id=?',(job_id,)).fetchone())

    # ------------------------------------------------------------------
    # snapshots and builds
    # ------------------------------------------------------------------

    def snapshot(self, destination: object) -> None:
        """Write a consistent SQLite backup of every table to ``destination``.

        The ``sqlite3`` backup API is used, so a live WAL file is never copied
        as a database backup.  The destination must not exist; a failed backup
        leaves whatever partial file SQLite created in place.
        """

        dest = _coerce_path(destination, 'destination')
        with self._lock:
            self._require_open()
            if os.path.lexists(dest):
                raise StoreViolation('destination_exists', f'destination already exists: {dest}')
            if os.path.normcase(str(dest)) == os.path.normcase(str(self._db_path)):
                raise StoreViolation('invalid_destination', 'destination is the live database')
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise StoreViolation('destination_unavailable', f'cannot create {dest.parent}: {error}') from error
            target = None
            try:
                from .PathGuard import safe_join
                safe_join(dest.parent, dest.name)
                with open(dest, 'xb'):
                    pass
                target = sqlite3.connect(
                    str(dest), timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None
                )
                self._connection.backup(target)
                target.commit()
            except sqlite3.Error as error:
                raise StoreViolation('snapshot_failed', str(error)) from error
            finally:
                if target is not None:
                    target.close()

    def record_build(self, record: Mapping) -> dict:
        """Record a build; an existing build_id never accepts a different digest."""

        if not isinstance(record, Mapping):
            raise StoreViolation('invalid_build_record', 'record must be a mapping')
        data = dict(record)
        for key in data:
            if not isinstance(key, str) or key == '':
                raise StoreViolation('invalid_build_record', 'build record keys must be non empty strings')
        _ensure_json_value(data, 'build record')
        if 'build_id' not in data:
            raise StoreViolation('invalid_build_record', 'build record requires build_id')
        build_id = _require_text(data['build_id'], 'build record build_id')
        digest = None
        for key in _BUILD_DIGEST_KEYS:
            candidate = data.get(key)
            if candidate not in (None, ''):
                digest = _require_text(candidate, f'build record {key}')
                break
        if digest is None:
            digest = hash_text(_canonical_json({key: value for key, value in data.items() if key != 'build_id'}))
        now = _utc_now()
        with self._write() as connection:
            row = connection.execute('SELECT * FROM builds WHERE build_id = ?', (build_id,)).fetchone()
            if row is not None:
                if row['input_digest'] != digest:
                    raise StoreViolation(
                        'build_conflict',
                        f'build {build_id} already exists with a different input digest',
                    )
                return _build_dict(row)
            connection.execute(
                'INSERT INTO builds (build_id, input_digest, record_json, created_at) VALUES (?, ?, ?, ?)',
                (build_id, digest, _canonical_json(data), now),
            )
        return {**data, 'input_digest': digest, 'recorded_at': now}

    def builds(self) -> list[dict]:
        rows = self._fetch_all('SELECT * FROM builds ORDER BY created_at, build_id')
        return [_build_dict(row) for row in rows]

    def latest_build_summary(self) -> dict | None:
        """Return the compact summary of the most recent build, if any.

        Only scalar JSON fields are read with SQLite ``json_extract``; the full
        record (which may contain large file, error and detail arrays) is never
        selected into Python or decoded.  Missing optional fields are ``None``.
        """

        row = self._fetch_one(
            "SELECT build_id, input_digest,"
            " json_extract(record_json, '$.project_id') AS project_id,"
            " json_extract(record_json, '$.output_path') AS output_path,"
            " json_extract(record_json, '$.mode') AS mode,"
            " json_extract(record_json, '$.runtime_validation') AS runtime_validation,"
            " created_at AS recorded_at"
            " FROM builds ORDER BY created_at DESC, build_id DESC LIMIT 1"
        )
        if row is None:
            return None
        return {
            'build_id': row['build_id'],
            'input_digest': row['input_digest'],
            'project_id': row['project_id'],
            'output_path': row['output_path'],
            'mode': row['mode'],
            'runtime_validation': row['runtime_validation'],
            'recorded_at': row['recorded_at'],
        }

    def get_build_record(self, build_id: str) -> dict | None:
        """Read one registered build for artifact verification, without history."""
        row = self._fetch_one('SELECT * FROM builds WHERE build_id = ?',
            (_require_text(build_id, 'build_id'),))
        return _build_dict(row) if row is not None else None


def _validated_new_metadata(metadata: Mapping) -> dict:
    if not isinstance(metadata, Mapping):
        raise StoreViolation('invalid_metadata', 'metadata must be a mapping')
    values = dict(metadata)
    for key in values:
        if not isinstance(key, str) or key == '':
            raise StoreViolation('invalid_metadata', 'metadata keys must be non empty strings')
    for key in ('project_id', 'source_root', 'engine'):
        if key not in values:
            raise StoreViolation('invalid_metadata', f'metadata requires {key!r}')
    values.setdefault('schema_version', SCHEMA_VERSION)
    values.setdefault('dataset_revision', 0)
    values.setdefault('content_revision', 0)
    version = values['schema_version']
    if type(version) is not int or version != SCHEMA_VERSION:
        raise StoreViolation(
            'unsupported_schema', f'schema_version must be {SCHEMA_VERSION}'
        )
    for key in ('project_id', 'source_root', 'engine'):
        values[key] = _require_text(values[key], f'metadata.{key}')
    for key in ('dataset_revision', 'content_revision'):
        values[key] = _require_count(values[key], f'metadata.{key}')
    declared = (
        _validated_feature_list(values[REQUIRED_FEATURES_KEY])
        if REQUIRED_FEATURES_KEY in values else []
    )
    if 'token_literals' in values:
        values['token_literals'] = _validated_literal_tokens(
            values['token_literals'], 'metadata.token_literals')
    if 'token_policy_id' in values:
        values['token_policy_id'] = _require_text(values['token_policy_id'], 'metadata.token_policy_id')
    if 'font_aliases' in values:
        from ModuleFolders.Domain.GameProject.FontPolicy import normalize_aliases
        values['font_aliases']=normalize_aliases(values['font_aliases'])
    if 'font_settings' in values:values['font_settings']=_validated_font_settings(values['font_settings'])
    profile_features=_validated_feature_list(values['profile_features']) if 'profile_features' in values else []
    if 'profile_features' in values:values['profile_features']=profile_features
    values[REQUIRED_FEATURES_KEY] = sorted(set(declared) | set(profile_features) | _required_features_for_profile(
        literal_tokens=values.get('token_literals'),
        policy_id=values.get('token_policy_id'),
        font_aliases=values.get('font_aliases'),font_settings=values.get('font_settings'),
    ))
    for key in list(values):
        values[key] = _normalize_metadata_value(values[key], f'metadata.{key}')
    return values
