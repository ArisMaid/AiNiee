"""Per-build resume journal for the frozen-input game build (contract v1).

This module implements ``docs/rpg/BUILD_RESUME_CONTRACT.md``: a per-build SQLite
journal stored at ``<project_root>/builds/<build_id>/resume.sqlite3``.  It
records the source/output SHA-256 pair of every staged file, the attempt
history and the files that were retained instead of reused.  A staged file is
only reported as reusable after its *actual* bytes have been re-hashed and match
the recorded output digest; progress counters, byte sizes and timestamps are
never trusted.

Engineering rules enforced here:

* every path goes through :func:`PathGuard.safe_join`, so traversal, alternate
  data streams, empty segments, reserved Windows device names, symlinks and
  junctions, and hard linked files are rejected instead of followed;
* one ``sqlite3`` connection per instance, guarded by a :class:`threading.RLock`,
  using ``BEGIN IMMEDIATE``, ``PRAGMA synchronous = FULL`` and
  ``PRAGMA journal_mode = DELETE`` (never WAL, so a single journal file never
  hides un-checkpointed data);
* the database file is created exclusively, never overwritten and never
  deleted; a journal whose schema marker or descriptor does not validate
  refuses to open instead of being rebuilt or overwritten;
* every SQL value is parameterized and every stored/read JSON document is
  parsed strictly, rejecting duplicate keys and ``NaN``/``Infinity``;
* the authoritative project database and the game's own files are never
  touched, no file content is ever logged, and nothing is ever deleted.

Error policy: domain rejections raise :class:`BuildJournalError` (a
``ValueError``) or :class:`PathGuard.PathViolation`; an exclusive-create
conflict raises ``FileExistsError``; a required-but-missing file raises
``FileNotFoundError``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .PathGuard import PathViolation, assert_disjoint, safe_join

__all__ = ['BuildJournal', 'BuildJournalError']

_BUILD_ID_PATTERN = re.compile(r'[a-f0-9]{32}')
_SHA256_PATTERN = re.compile(r'[a-f0-9]{64}')
_DB_NAME = 'resume.sqlite3'
_STAGING_PREFIX = '.staging-'
_SCHEMA_VERSION = 1
_REASON_LIMIT = 4096
_JSON_DEPTH_LIMIT = 64
_READ_BLOCK = 1024 * 1024
_REPARSE_FLAG = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
_RUNNING_STATE = 'RUNNING'
_TERMINAL_STATES = frozenset({'COMPLETED', 'FAILED', 'CANCELLED', 'INTERRUPTED'})
_DESCRIPTOR_KEYS = frozenset({
    'schema_version',
    'build_id',
    'project_id',
    'output_root',
    'source_root',
    'test',
    'runtime_capture',
    'frozen_sha256',
    'plan_digest',
})
_META_KEYS = frozenset({'journal_schema', 'build_id', 'descriptor'})


class BuildJournalError(ValueError):
    """Raised when a journal, its descriptor, or an operation is rejected.

    A ``ValueError`` subtype carrying a stable, machine readable :attr:`code`.
    """

    def __init__(self, code: str, message: str = '') -> None:
        self.code = str(code)
        super().__init__(str(message) or self.code)


# ---------------------------------------------------------------------------
# generic validation helpers
# ---------------------------------------------------------------------------

def _path_text(value: object, name: str) -> str:
    """Return ``value`` as a ``str`` path, rejecting bytes and NUL."""

    if isinstance(value, (bytes, bytearray)):
        raise BuildJournalError('path_invalid', f'{name} must be a string path, not bytes')
    try:
        text = os.fspath(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise BuildJournalError(
            'path_invalid', f'{name} must be a path-like value, got {type(value).__name__}'
        ) from error
    if isinstance(text, bytes):
        raise BuildJournalError('path_invalid', f'{name} must be a string path, not bytes')
    if text == '':
        raise BuildJournalError('path_invalid', f'{name} must not be empty')
    if '\x00' in text:
        raise BuildJournalError('path_invalid', f'{name} must not contain NUL')
    return text


def _require_id(value: object, name: str = 'build_id') -> str:
    """Require a strict 32 character lowercase hex identifier."""

    if not isinstance(value, str) or _BUILD_ID_PATTERN.fullmatch(value) is None:
        raise BuildJournalError(f'{name}_invalid', f'{name} must be 32 lowercase hex characters')
    return value


def _require_digest(value: object, name: str) -> str:
    """Require a lowercase SHA-256 hex digest."""

    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise BuildJournalError('sha256_invalid', f'{name} must be a lowercase SHA-256 hex digest')
    return value


def _canonical_relative_text(value: object, name: str = 'relative_path') -> str:
    """Require a canonical ``/`` separated relative path (lexical checks only).

    Traversal, empty segments, reserved device names, ADS and invalid characters
    are rejected by :func:`PathGuard.safe_join` when the path is joined.
    """

    text = _path_text(value, name)
    if '\\' in text:
        raise BuildJournalError(
            'path_not_canonical', f'{name} must use "/" separators: {text!r}'
        )
    if text.startswith('/'):
        raise BuildJournalError('path_absolute', f'{name} must be relative: {text!r}')
    if text.endswith('/') or '//' in text:
        raise BuildJournalError(
            'path_empty_segment', f'{name} must not contain empty segments: {text!r}'
        )
    return text


def _validated_relative_text(value: object, root: object, name: str = 'relative_path') -> str:
    """Return a canonical relative path that :func:`safe_join` accepts under ``root``."""

    text = _canonical_relative_text(value, name)
    safe_join(root, text)
    return text


def _validate_json_value(value: object, what: str, depth: int = 0) -> None:
    """Reject values that cannot round-trip through strict JSON."""

    if depth > _JSON_DEPTH_LIMIT:
        raise BuildJournalError('json_too_deep', f'{what} is nested too deeply')
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise BuildJournalError(
                'json_constant', f'{what} must not contain NaN or Infinity'
            )
        return
    if isinstance(value, str):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item, what, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise BuildJournalError('json_key_invalid', f'{what} keys must be strings')
            _validate_json_value(item, what, depth + 1)
        return
    raise BuildJournalError(
        'json_invalid', f'{what} contains a non-JSON value of type {type(value).__name__}'
    )


def _dump_json(value: object, what: str) -> str:
    """Serialize ``value`` as strict deterministic JSON (no NaN/Infinity)."""

    _validate_json_value(value, what)
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')
        )
    except (TypeError, ValueError) as error:
        raise BuildJournalError('json_invalid', f'{what} could not be encoded as JSON') from error


def _strict_json_loads(text: object, what: str) -> object:
    """Parse JSON text, rejecting duplicate keys and ``NaN``/``Infinity``."""

    if not isinstance(text, str):
        raise BuildJournalError('json_invalid', f'{what} must be stored as JSON text')

    def _pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BuildJournalError(
                    'json_duplicate_key', f'{what} contains a duplicate JSON key: {key!r}'
                )
            result[key] = value
        return result

    def _constant(name):
        raise BuildJournalError(
            'json_constant', f'{what} contains the JSON constant {name}'
        )

    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except BuildJournalError:
        raise
    except (ValueError, TypeError) as error:
        raise BuildJournalError('json_invalid', f'{what} is not valid JSON') from error


def _validate_writer(writer: object) -> str:
    """Validate a ``writer`` mapping and return its canonical JSON text."""

    if not isinstance(writer, dict):
        raise BuildJournalError('writer_invalid', 'writer must be a JSON object (dict)')
    _validate_json_value(writer, 'writer')
    identifier = writer.get('id')
    if not isinstance(identifier, str) or identifier.strip() == '':
        raise BuildJournalError(
            'writer_invalid', "writer must contain a non-empty string 'id'"
        )
    return _dump_json(writer, 'writer')


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _is_reparse(stat_result: os.stat_result) -> bool:
    if stat.S_ISLNK(stat_result.st_mode):
        return True
    return bool(getattr(stat_result, 'st_file_attributes', 0) & _REPARSE_FLAG)


def _lstat_or_none(path: object) -> os.stat_result | None:
    """``os.lstat`` that fails closed (returns ``None``) on any stat error."""

    try:
        return os.lstat(path)
    except OSError:
        return None


def _hash_regular_file(path: object) -> str | None:
    """Return the SHA-256 of ``path``'s bytes, or ``None`` if it is unreadable.

    Contents are never returned or logged; only the digest is produced.  A hard
    linked or non-regular opened file is a violation and is rejected.
    """

    try:
        with open(path, 'rb') as handle:
            stat_result = os.fstat(handle.fileno())
            if not stat.S_ISREG(stat_result.st_mode):
                return None
            if getattr(stat_result, 'st_nlink', 1) > 1:
                raise PathViolation(
                    'hardlink_not_allowed', f'hard linked files are not allowed: {path}'
                )
            digest = hashlib.sha256()
            for block in iter(lambda: handle.read(_READ_BLOCK), b''):
                digest.update(block)
            return digest.hexdigest()
    except PathViolation:
        raise
    except OSError:
        return None


# ---------------------------------------------------------------------------
# descriptor / project root validation
# ---------------------------------------------------------------------------

def _require_directory(value: object, name: str) -> str:
    """Require an existing directory, returned as an absolute normalized path."""

    text = _path_text(value, name)
    path = Path(os.path.abspath(text))
    if not os.path.isdir(path):
        raise FileNotFoundError(f'{name} must be an existing directory: {path}')
    return str(path)


def _require_records_root(project_root: object, build_id: str) -> Path:
    """Return ``builds/<build_id>``; the directory must already exist."""

    records_root = safe_join(project_root, f'builds/{build_id}')
    if not os.path.isdir(records_root):
        raise FileNotFoundError(f'records root must already exist: {records_root}')
    return records_root


def _require_absolute_root(value: object, name: str) -> str:
    text = _path_text(value, name)
    if not os.path.isabs(text):
        raise BuildJournalError(
            'descriptor_root_not_absolute', f'descriptor {name} must be an absolute path'
        )
    if os.name == 'nt' and os.path.splitdrive(text)[0] == '':
        raise BuildJournalError(
            'descriptor_root_not_absolute',
            f'descriptor {name} must be a fully qualified absolute path',
        )
    return text


def _validate_descriptor(descriptor: object, project_root: object, build_id: str):
    """Validate the frozen descriptor and its path boundaries.

    Returns ``(output_root, source_root)``.  Unknown or missing keys, wrong
    types, mismatched ids, non-absolute roots, overlapping roots and malformed
    digests are all rejected.  The descriptor never carries a game encryption
    key: the key set is exact and closed.
    """

    if not isinstance(descriptor, dict):
        raise BuildJournalError('descriptor_invalid', 'descriptor must be a JSON object (dict)')
    keys = set(descriptor)
    if keys != _DESCRIPTOR_KEYS:
        missing = sorted(_DESCRIPTOR_KEYS - keys)
        unknown = sorted(str(key) for key in keys - _DESCRIPTOR_KEYS)
        raise BuildJournalError(
            'descriptor_keys',
            f'descriptor keys must be exactly {sorted(_DESCRIPTOR_KEYS)};'
            f' missing={missing} unknown={unknown}',
        )
    version = descriptor['schema_version']
    if type(version) is not int or version != _SCHEMA_VERSION:
        raise BuildJournalError(
            'descriptor_schema_version', 'descriptor schema_version must be the integer 1'
        )
    stored_build_id = descriptor['build_id']
    if not isinstance(stored_build_id, str) or stored_build_id == '':
        raise BuildJournalError(
            'descriptor_build_id', 'descriptor build_id must be a non-empty string'
        )
    if stored_build_id != build_id:
        raise BuildJournalError(
            'descriptor_build_id', 'descriptor build_id must match the requested build id'
        )
    project_id = descriptor['project_id']
    if not isinstance(project_id, str) or project_id == '':
        raise BuildJournalError(
            'descriptor_project_id', 'descriptor project_id must be a non-empty string'
        )
    output_root = _require_absolute_root(descriptor['output_root'], 'output_root')
    source_root = _require_absolute_root(descriptor['source_root'], 'source_root')
    for name in ('test', 'runtime_capture'):
        if type(descriptor[name]) is not bool:
            raise BuildJournalError(
                'descriptor_flag', f'descriptor {name} must be exactly a bool'
            )
    _require_digest(descriptor['frozen_sha256'], 'frozen_sha256')
    _require_digest(descriptor['plan_digest'], 'plan_digest')
    assert_disjoint(source_root, project_root, output_root)
    return output_root, source_root


# ---------------------------------------------------------------------------
# SQLite plumbing
# ---------------------------------------------------------------------------

_SQL_SET_USER_VERSION = 'PRAGMA user_version = 1'
_SQL_INSERT_META = 'INSERT INTO journal_meta(key, value) VALUES(?, ?)'
_SQL_META = 'SELECT key, value FROM journal_meta'
_SQL_USER_VERSION = 'PRAGMA user_version'

_SQL_ATTEMPT_EXISTS = 'SELECT 1 FROM attempts WHERE attempt_id = ?'
_SQL_INSERT_ATTEMPT = (
    'INSERT INTO attempts(attempt_id, job_id, state, reason, created_utc, finished_utc)'
    ' VALUES(?, ?, ?, ?, ?, NULL)'
)
_SQL_ATTEMPT_STATE = 'SELECT state, reason FROM attempts WHERE attempt_id = ?'
_SQL_FINISH_ATTEMPT = (
    'UPDATE attempts SET state = ?, reason = ?, finished_utc = ? WHERE attempt_id = ?'
)
_SQL_ATTEMPT = (
    'SELECT job_id, state, reason, created_utc, finished_utc FROM attempts WHERE attempt_id = ?'
)
_SQL_ALL_ATTEMPTS = (
    'SELECT attempt_id, job_id, state, reason, created_utc, finished_utc FROM attempts'
    ' ORDER BY created_utc, attempt_id'
)

_SQL_FILE_BY_KEY = 'SELECT relative_path FROM files WHERE path_key = ?'
_SQL_FILE_BY_PATH = (
    'SELECT relative_path, original_sha256, output_sha256, writer FROM files'
    ' WHERE relative_path = ?'
)
_SQL_ALL_FILES = 'SELECT relative_path, original_sha256, output_sha256, writer FROM files'
_SQL_INSERT_FILE = (
    'INSERT INTO files(relative_path, path_key, original_sha256, output_sha256, writer, updated_utc)'
    ' VALUES(?, ?, ?, ?, ?, ?)'
    ' ON CONFLICT(relative_path) DO UPDATE SET'
    ' original_sha256 = excluded.original_sha256,'
    ' output_sha256 = excluded.output_sha256,'
    ' writer = excluded.writer,'
    ' updated_utc = excluded.updated_utc'
)

_SQL_INSERT_RETAINED = (
    'INSERT INTO retained(retained_path, relative_path, attempt_id, created_utc)'
    ' VALUES(?, ?, ?, ?)'
)
_SQL_ALL_RETAINED = (
    'SELECT retained_path, relative_path, attempt_id, created_utc FROM retained'
    ' ORDER BY retained_path'
)

_SCHEMA_STATEMENTS = (
    'CREATE TABLE journal_meta ('
    ' key TEXT PRIMARY KEY NOT NULL,'
    ' value TEXT NOT NULL)',
    'CREATE TABLE attempts ('
    ' attempt_id TEXT PRIMARY KEY NOT NULL,'
    ' job_id TEXT NOT NULL,'
    ' state TEXT NOT NULL,'
    ' reason TEXT NOT NULL,'
    ' created_utc TEXT NOT NULL,'
    ' finished_utc TEXT NULL)',
    'CREATE TABLE files ('
    ' relative_path TEXT PRIMARY KEY NOT NULL,'
    ' path_key TEXT NOT NULL UNIQUE,'
    ' original_sha256 TEXT NOT NULL,'
    ' output_sha256 TEXT NOT NULL,'
    ' writer TEXT NOT NULL,'
    ' updated_utc TEXT NOT NULL)',
    'CREATE TABLE retained ('
    ' retained_path TEXT PRIMARY KEY NOT NULL,'
    ' relative_path TEXT NOT NULL,'
    ' attempt_id TEXT NOT NULL,'
    ' created_utc TEXT NOT NULL)',
    'CREATE INDEX attempts_job_id_index ON attempts(job_id)',
    'CREATE INDEX retained_relative_path_index ON retained(relative_path)',
)

_SCHEMA_CHECKS = (
    ('journal_meta', 'PRAGMA table_info(journal_meta)', ('key', 'value')),
    (
        'attempts',
        'PRAGMA table_info(attempts)',
        ('attempt_id', 'job_id', 'state', 'reason', 'created_utc', 'finished_utc'),
    ),
    (
        'files',
        'PRAGMA table_info(files)',
        ('relative_path', 'path_key', 'original_sha256', 'output_sha256', 'writer', 'updated_utc'),
    ),
    (
        'retained',
        'PRAGMA table_info(retained)',
        ('retained_path', 'relative_path', 'attempt_id', 'created_utc'),
    ),
)


def _rollback(connection: sqlite3.Connection) -> None:
    """Best effort rollback; the original failure is always re-raised by callers."""

    try:
        connection.execute('ROLLBACK')
    except sqlite3.Error:
        pass


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open one private connection with the contract's durability pragmas."""

    connection = sqlite3.connect(
        str(db_path), timeout=5.0, isolation_level=None, check_same_thread=False
    )
    try:
        mode_row = connection.execute('PRAGMA journal_mode = DELETE').fetchone()
        if mode_row is None or str(mode_row[0]).lower() != 'delete':
            raise BuildJournalError(
                'journal_mode_invalid', 'journal_mode must be DELETE; WAL is not allowed'
            )
        connection.execute('PRAGMA synchronous = FULL')
        sync_row = connection.execute('PRAGMA synchronous').fetchone()
        if sync_row is None or sync_row[0] != 2:
            raise BuildJournalError('journal_sync_invalid', 'synchronous must be FULL')
    except BaseException:
        connection.close()
        raise
    return connection


def _initialize(connection: sqlite3.Connection, build_id: str, descriptor: dict) -> None:
    """Create the v1 schema and the schema marker/descriptor rows."""

    connection.execute('BEGIN IMMEDIATE')
    try:
        for statement in _SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute(_SQL_SET_USER_VERSION)
        values = (
            ('journal_schema', str(_SCHEMA_VERSION)),
            ('build_id', build_id),
            ('descriptor', _dump_json(descriptor, 'descriptor')),
        )
        for key, value in values:
            connection.execute(_SQL_INSERT_META, (key, value))
        connection.execute('COMMIT')
    except BaseException:
        _rollback(connection)
        raise


def _verify_schema(connection: sqlite3.Connection) -> None:
    """Refuse to open a database whose schema marker or tables are not v1."""

    version_row = connection.execute(_SQL_USER_VERSION).fetchone()
    value = version_row[0] if version_row is not None else None
    if type(value) is not int or value != _SCHEMA_VERSION:
        raise BuildJournalError(
            'journal_schema_invalid', 'journal schema version marker is not 1'
        )
    for table, sql, expected in _SCHEMA_CHECKS:
        rows = connection.execute(sql).fetchall()
        columns = tuple(row[1] for row in rows)
        if columns != expected:
            raise BuildJournalError(
                'journal_schema_invalid', f'unexpected columns in journal table {table!r}'
            )


def _load_descriptor(connection: sqlite3.Connection, project_root: object, build_id: str) -> dict:
    """Read and fully re-validate the stored schema marker and descriptor."""

    found = {}
    for key, value in connection.execute(_SQL_META).fetchall():
        if not isinstance(key, str):
            raise BuildJournalError('journal_meta_invalid', 'journal meta keys must be text')
        if key in found:
            raise BuildJournalError('journal_meta_invalid', f'duplicate journal meta key: {key!r}')
        found[key] = value
    if set(found) != _META_KEYS:
        raise BuildJournalError(
            'journal_meta_invalid', f'journal meta keys must be exactly {sorted(_META_KEYS)}'
        )
    if found['journal_schema'] != str(_SCHEMA_VERSION):
        raise BuildJournalError('journal_schema_invalid', 'journal schema marker is not 1')
    stored_build_id = found['build_id']
    if not isinstance(stored_build_id, str) or _BUILD_ID_PATTERN.fullmatch(stored_build_id) is None:
        raise BuildJournalError(
            'journal_build_mismatch', 'journal build id is not 32 lowercase hex characters'
        )
    if stored_build_id != build_id:
        raise BuildJournalError('journal_build_mismatch', 'journal belongs to a different build id')
    descriptor = _strict_json_loads(found['descriptor'], 'journal descriptor')
    _validate_descriptor(descriptor, project_root, build_id)
    return descriptor


def _allocate_id(connection: sqlite3.Connection, exists_sql: str) -> str:
    """Return a fresh 32 hex id that is not present in the journal."""

    for _ in range(8):
        candidate = uuid.uuid4().hex
        if connection.execute(exists_sql, (candidate,)).fetchone() is None:
            return candidate
    raise BuildJournalError('id_allocation_failed', 'could not allocate a unique 32 hex id')


def _record_from_row(row, staging: object) -> dict:
    """Validate one stored file row and return a manifest compatible record."""

    path = _validated_relative_text(row[0], staging, 'record.path')
    original = _require_digest(row[1], 'record.original_sha256')
    output = _require_digest(row[2], 'record.output_sha256')
    writer = _strict_json_loads(row[3], 'record.writer')
    _validate_writer(writer)
    return {
        'path': path,
        'original_sha256': original,
        'output_sha256': output,
        'changed': original != output,
        'writer': writer,
    }


# ---------------------------------------------------------------------------
# BuildJournal
# ---------------------------------------------------------------------------

class BuildJournal:
    """A single build's persistent resume journal.

    Instances are obtained from :meth:`create` (new journal) or :meth:`open`
    (existing journal), are context managers and expose :meth:`close`.
    """

    def __init__(
        self,
        project_root: object,
        build_id: str,
        descriptor: dict,
        *,
        connection: sqlite3.Connection,
        db_path: object,
        records_root: object,
        output_root: object,
        staging: object,
    ) -> None:
        self._project_root = str(project_root)
        self._build_id = build_id
        self._descriptor = copy.deepcopy(descriptor)
        self._connection: sqlite3.Connection | None = connection
        self._db_path = Path(db_path)
        self._records_root = Path(records_root)
        self._output_root = str(output_root)
        self._staging = Path(staging)
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def create(cls, project_root: object, build_id: str, descriptor: dict) -> 'BuildJournal':
        """Create a new journal; the database file must not exist yet.

        The record root ``builds/<build_id>`` must already exist.  The database
        placeholder is created exclusively and is retained for diagnostics even
        when initialization fails afterwards: this module never deletes files
        and never overwrites an existing journal.
        """

        root_text = _require_directory(project_root, 'project_root')
        _require_id(build_id, 'build_id')
        output_root, _source_root = _validate_descriptor(descriptor, root_text, build_id)
        staging = safe_join(output_root, _STAGING_PREFIX + build_id)
        records_root = _require_records_root(root_text, build_id)
        db_path = safe_join(records_root, _DB_NAME)
        if os.path.lexists(db_path):
            raise FileExistsError(f'journal already exists: {db_path}')
        stored_descriptor = copy.deepcopy(descriptor)
        connection: sqlite3.Connection | None = None
        try:
            handle = os.open(db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(handle)
            connection = _connect(db_path)
            _initialize(connection, build_id, stored_descriptor)
        except BaseException:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            raise
        return cls(
            root_text,
            build_id,
            stored_descriptor,
            connection=connection,
            db_path=db_path,
            records_root=records_root,
            output_root=output_root,
            staging=staging,
        )

    @classmethod
    def open(cls, project_root: object, build_id: str) -> 'BuildJournal':
        """Open an existing journal and re-validate descriptor and boundaries.

        A missing database is never created implicitly and a journal whose
        schema marker or descriptor does not validate refuses to open.
        """

        root_text = _require_directory(project_root, 'project_root')
        _require_id(build_id, 'build_id')
        records_root = _require_records_root(root_text, build_id)
        db_path = safe_join(records_root, _DB_NAME)
        if not os.path.lexists(db_path):
            raise FileNotFoundError(f'journal does not exist: {db_path}')
        if not stat.S_ISREG(os.lstat(db_path).st_mode):
            raise BuildJournalError('journal_not_file', f'journal is not a regular file: {db_path}')
        connection = _connect(db_path)
        try:
            _verify_schema(connection)
            stored_descriptor = _load_descriptor(connection, root_text, build_id)
            staging = safe_join(
                stored_descriptor['output_root'], _STAGING_PREFIX + build_id
            )
        except BaseException:
            try:
                connection.close()
            except Exception:
                pass
            raise
        return cls(
            root_text,
            build_id,
            stored_descriptor,
            connection=connection,
            db_path=db_path,
            records_root=records_root,
            output_root=stored_descriptor['output_root'],
            staging=staging,
        )

    def close(self) -> None:
        """Close this instance's connection; safe to call more than once."""

        with self._lock:
            connection = self._connection
            self._connection = None
        if connection is not None:
            connection.close()

    def __enter__(self) -> 'BuildJournal':
        self._ensure_open()
        return self

    def __exit__(self, *_exc) -> bool:
        self.close()
        return False

    def __del__(self) -> None:
        connection = getattr(self, '_connection', None)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    # -- read-only views ---------------------------------------------------

    @property
    def descriptor(self) -> dict:
        """A read-only deep copy of the validated descriptor."""

        return copy.deepcopy(self._descriptor)

    @property
    def build_id(self) -> str:
        return self._build_id

    @property
    def project_root(self) -> Path:
        return Path(self._project_root)

    @property
    def records_root(self) -> Path:
        return self._records_root

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def staging(self) -> Path:
        """The staging directory uniquely bound to ``output_root/.staging-<id>``."""

        return self._staging

    @property
    def closed(self) -> bool:
        return self._connection is None

    # -- attempts ----------------------------------------------------------

    def new_attempt(self, job_id: str) -> str:
        """Persist a fresh RUNNING attempt for ``job_id`` and return its id.

        ``job_id`` must be 32 lowercase hex.  A new attempt id is always
        allocated; existing attempt records are never reused.
        """

        job = _require_id(job_id, 'job_id')
        with self._write_transaction() as connection:
            attempt_id = _allocate_id(connection, _SQL_ATTEMPT_EXISTS)
            connection.execute(
                _SQL_INSERT_ATTEMPT, (attempt_id, job, _RUNNING_STATE, '', _now_utc())
            )
        return attempt_id

    def finish_attempt(self, attempt_id: str, state: str, reason: str = '') -> None:
        """Move an attempt to a terminal state and record the audit trail.

        ``state`` must be one of ``COMPLETED``/``FAILED``/``CANCELLED``/
        ``INTERRUPTED``.  A finished attempt cannot change its state or reason;
        repeating the exact same state and reason is an idempotent no-op.
        """

        attempt = _require_id(attempt_id, 'attempt_id')
        if not isinstance(state, str) or state not in _TERMINAL_STATES:
            raise BuildJournalError(
                'attempt_state_invalid',
                f'state must be one of {sorted(_TERMINAL_STATES)}',
            )
        if not isinstance(reason, str):
            raise BuildJournalError('attempt_reason_invalid', 'reason must be a string')
        if len(reason) > _REASON_LIMIT:
            raise BuildJournalError(
                'attempt_reason_too_long', f'reason must be at most {_REASON_LIMIT} characters'
            )
        with self._write_transaction() as connection:
            row = connection.execute(_SQL_ATTEMPT_STATE, (attempt,)).fetchone()
            if row is None:
                raise BuildJournalError('attempt_unknown', f'unknown attempt_id: {attempt}')
            current_state, current_reason = row[0], row[1]
            if current_state in _TERMINAL_STATES:
                if current_state == state and current_reason == reason:
                    return
                raise BuildJournalError(
                    'attempt_finalized',
                    f'attempt {attempt} already finished as {current_state}',
                )
            connection.execute(
                _SQL_FINISH_ATTEMPT, (state, reason, _now_utc(), attempt)
            )

    def attempt(self, attempt_id: str) -> dict:
        """Return the audit record of one attempt (read-only helper)."""

        attempt = _require_id(attempt_id, 'attempt_id')
        row = self._fetchone(_SQL_ATTEMPT, (attempt,))
        if row is None:
            raise BuildJournalError('attempt_unknown', f'unknown attempt_id: {attempt}')
        return {
            'attempt_id': attempt,
            'job_id': row[0],
            'state': row[1],
            'reason': row[2],
            'created_utc': row[3],
            'finished_utc': row[4],
        }

    def attempts(self) -> list[dict]:
        """Return every attempt audit record, oldest first (read-only helper)."""

        return [
            {
                'attempt_id': row[0],
                'job_id': row[1],
                'state': row[2],
                'reason': row[3],
                'created_utc': row[4],
                'finished_utc': row[5],
            }
            for row in self._fetchall(_SQL_ALL_ATTEMPTS)
        ]

    # -- staged file records ----------------------------------------------

    def record_file(
        self,
        relative_path: str,
        original_sha256: str,
        output_sha256: str,
        writer: dict,
    ) -> None:
        """Upsert the recorded digest pair and writer for one staged file.

        ``relative_path`` is relative to the descriptor staging directory and
        must be canonical ``/``; case-folded collisions, reserved names, ADS,
        links and traversal are rejected.  Both digests must be lowercase
        SHA-256 and ``writer`` must be strict JSON with a non-empty string
        ``id``.  Only the journal database is written here, never a game file.
        """

        relative = _validated_relative_text(relative_path, self._staging)
        original = _require_digest(original_sha256, 'original_sha256')
        output = _require_digest(output_sha256, 'output_sha256')
        writer_json = _validate_writer(writer)
        timestamp = _now_utc()
        path_key = relative.casefold()
        with self._write_transaction() as connection:
            existing = connection.execute(_SQL_FILE_BY_KEY, (path_key,)).fetchone()
            if existing is not None and existing[0] != relative:
                raise BuildJournalError(
                    'path_case_collision',
                    f'relative_path collides case-insensitively with {existing[0]!r}',
                )
            connection.execute(
                _SQL_INSERT_FILE,
                (relative, path_key, original, output, writer_json, timestamp),
            )

    def records(self) -> list[dict]:
        """Return the recorded manifest entries sorted by path.

        Each entry is ``{path, original_sha256, output_sha256, changed, writer}``
        compatible with the ``BuildService`` manifest.  ``changed`` compares the
        recorded digests themselves; stored JSON and fields are re-validated and
        a corrupt row is refused rather than silently reported.
        """

        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(_SQL_ALL_FILES).fetchall()
        entries = [_record_from_row(row, self._staging) for row in rows]
        return sorted(entries, key=lambda entry: entry['path'])

    def reusable_file(
        self, staging: object, relative_path: str, original_sha256: str
    ) -> dict | None:
        """Return the recorded entry when a staged file may be reused.

        ``None`` is returned when there is no record with the given source hash,
        when the staged file is missing or not a regular file, or when its
        actual bytes do not hash to the recorded output SHA-256.  Symlink,
        junction and hard link violations are rejected instead of ignored; the
        staging directory must be exactly the descriptor's staging directory.
        Directory targets are never hashed and never returned.
        """

        with self._lock:
            self._ensure_open()
            root = self._bind_staging(staging)
            relative = _canonical_relative_text(relative_path)
            expected_original = _require_digest(original_sha256, 'original_sha256')
            target = safe_join(root, relative)
            row = self._connection.execute(_SQL_FILE_BY_PATH, (relative,)).fetchone()
            if row is None:
                return None
            record = _record_from_row(row, root)
            if record['original_sha256'] != expected_original:
                return None
            stat_result = _lstat_or_none(target)
            if stat_result is None or not stat.S_ISREG(stat_result.st_mode):
                return None
            if _is_reparse(stat_result):
                raise PathViolation(
                    'reparse_point', f'symlinks and junctions are not allowed: {target}'
                )
            if getattr(stat_result, 'st_nlink', 1) > 1:
                raise PathViolation(
                    'hardlink_not_allowed', f'hard linked files are not allowed: {target}'
                )
            actual = _hash_regular_file(target)
            if actual is None or actual != record['output_sha256']:
                return None
            return record

    def retain_file(self, staging: object, relative_path: str, attempt_id: str) -> str:
        """Rename one non-reused staging file into ``retained/<attempt>/``.

        A single file rename on one filesystem is used; nothing is recursive,
        nothing is deleted and an existing target is never silently overwritten.
        The audit row (original relative path, retained path, timestamp) is
        written in its own transaction after the rename.  If the rename succeeds
        but the audit row cannot be written, :class:`BuildJournalError` is
        raised with code ``retain_audit_failed`` and the retained file is kept
        as it is; the move is never retried.  Returns the project relative
        retained path.
        """

        with self._lock:
            self._ensure_open()
            root = self._bind_staging(staging)
            relative = _canonical_relative_text(relative_path)
            attempt = _require_id(attempt_id, 'attempt_id')
            source = safe_join(root, relative)
            source_stat = os.lstat(source)
            if stat.S_ISDIR(source_stat.st_mode):
                raise IsADirectoryError(
                    f'retain_file requires a regular staging file, not a directory: {relative}'
                )
            if _is_reparse(source_stat):
                raise PathViolation(
                    'reparse_point', f'symlinks and junctions are not allowed: {source}'
                )
            if not stat.S_ISREG(source_stat.st_mode):
                raise BuildJournalError(
                    'retain_not_regular', f'retain_file requires a regular staging file: {relative}'
                )
            if getattr(source_stat, 'st_nlink', 1) > 1:
                raise PathViolation(
                    'hardlink_not_allowed', f'hard linked files are not allowed: {source}'
                )
            if self._fetchone(_SQL_ATTEMPT_EXISTS, (attempt,)) is None:
                raise BuildJournalError('attempt_unknown', f'unknown attempt_id: {attempt}')
            retained_name = uuid.uuid4().hex + '.bin'
            relative_retained = f'retained/{attempt}/{retained_name}'
            target = safe_join(self._records_root, relative_retained)
            target.parent.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(target):
                raise FileExistsError(f'retained file already exists: {relative_retained}')
            target_stat = os.stat(target.parent)
            if getattr(source_stat, 'st_dev', None) != getattr(target_stat, 'st_dev', None):
                raise BuildJournalError(
                    'retain_cross_device',
                    'retain_file requires the staging file and the retained directory'
                    ' on one filesystem',
                )
            os.rename(source, target)
            retained_relative_path = f'builds/{self._build_id}/{relative_retained}'
            try:
                with self._write_transaction() as connection:
                    connection.execute(
                        _SQL_INSERT_RETAINED,
                        (retained_relative_path, relative, attempt, _now_utc()),
                    )
            except Exception as error:
                raise BuildJournalError(
                    'retain_audit_failed',
                    f'file was retained at {retained_relative_path} but its audit record'
                    f' could not be written: {error}',
                ) from error
            return retained_relative_path

    def retained_files(self) -> list[dict]:
        """Return the retained file audit rows (read-only helper)."""

        return [
            {
                'retained_path': row[0],
                'relative_path': row[1],
                'attempt_id': row[2],
                'created_utc': row[3],
            }
            for row in self._fetchall(_SQL_ALL_RETAINED)
        ]

    # -- internals ---------------------------------------------------------

    @contextmanager
    def _write_transaction(self):
        with self._lock:
            self._ensure_open()
            connection = self._connection
            connection.execute('BEGIN IMMEDIATE')
            try:
                yield connection
            except BaseException:
                _rollback(connection)
                raise
            try:
                connection.execute('COMMIT')
            except BaseException:
                _rollback(connection)
                raise

    def _fetchone(self, sql: str, parameters=()):
        with self._lock:
            self._ensure_open()
            return self._connection.execute(sql, parameters).fetchone()

    def _fetchall(self, sql: str, parameters=()):
        with self._lock:
            self._ensure_open()
            return self._connection.execute(sql, parameters).fetchall()

    def _ensure_open(self) -> None:
        if self._connection is None:
            raise BuildJournalError('journal_closed', 'the build journal is closed')

    def _bind_staging(self, staging: object) -> Path:
        """Prove ``staging`` is the descriptor staging directory, then re-validate it."""

        text = _path_text(staging, 'staging')
        provided = os.path.normcase(os.path.normpath(os.path.abspath(text)))
        bound = os.path.normcase(os.path.normpath(str(self._staging)))
        if provided != bound:
            raise BuildJournalError(
                'staging_mismatch',
                f'staging must be the descriptor staging directory {self._staging}',
            )
        return safe_join(self._output_root, _STAGING_PREFIX + self._build_id)
