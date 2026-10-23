"""Registered atomic output writes for the frozen-input game build (contract v1).

Every output write first commits a small registration marker outside the output
tree.  The marker names exactly one output staging file and is the only durable
provenance this module trusts.  Recovery validates every final marker before it
moves anything, records a proof for the actual retained bytes and then renames
exactly that one file into ``atomic-retained``.  A retained staging file is never
published as a completed output and no evidence file is deleted, copied,
chmodded or overwritten during recovery.

Error policy: validation and evidence failures raise ``ValueError`` with a
stable ``BUILD_ATOMIC_*`` message prefix.  A same-filesystem rename that cannot
be completed leaves the marker, proof and temporary in place for inspection and
a later recovery attempt.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import stat
import uuid
from pathlib import Path

from . import PathGuard

__all__ = ['BuildAtomicWriter']

_SCHEMA_VERSION = 1
_ID_PATTERN = re.compile(r'[a-f0-9]{32}')
_SHA256_PATTERN = re.compile(r'[a-f0-9]{64}')
_FINAL_MARKER_PATTERN = re.compile(r'[a-f0-9]{32}\.json')
_FINAL_ARCHIVE_PATTERN = re.compile(r'[a-f0-9]{32}\.bin')
_MAX_JSON_BYTES = 16 * 1024
_READ_BLOCK = 1024 * 1024
_REPARSE_FLAG = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
_ATOMIC_WRITES = 'atomic-writes'
_ATOMIC_RETAINED = 'atomic-retained'
_ATOMIC_RECOVERY = 'atomic-recovery'
_MARKER_KEYS = frozenset({
    'schema_version',
    'build_id',
    'attempt_id',
    'write_id',
    'plan_digest',
    'frozen_sha256',
    'target',
    'temporary',
    'payload_sha256',
    'payload_size',
})
_PROOF_KEYS = frozenset({
    'schema_version',
    'build_id',
    'write_id',
    'marker_sha256',
    'actual_sha256',
    'actual_size',
})


def _fail(code: str, message: str) -> None:
    """Raise a domain rejection with a stable, machine readable prefix."""

    raise PathGuard.PathViolation(code, f'{code}: {message}')


def _path_text(value: object, name: str) -> str:
    """Return a string path, rejecting bytes, empty text and NUL."""

    if isinstance(value, (bytes, bytearray)):
        _fail('BUILD_ATOMIC_PATH_INVALID', f'{name} must be a string path, not bytes')
    try:
        text = os.fspath(value)  # type: ignore[arg-type]
    except TypeError as error:
        _fail(
            'BUILD_ATOMIC_PATH_INVALID',
            f'{name} must be a path-like value, got {type(value).__name__}',
        )
    if not isinstance(text, str) or text == '' or '\x00' in text:
        _fail('BUILD_ATOMIC_PATH_INVALID', f'{name} must be a non-empty string path without NUL')
    return text


def _canonical_relative(value: object, name: str) -> str:
    """Require an already canonical ``/``-separated relative POSIX path."""

    if type(value) is not str:
        _fail('BUILD_ATOMIC_PATH_INVALID', f'{name} must be a string relative path')
    if value == '':
        _fail('BUILD_ATOMIC_PATH_ROOT', f'{name} must not name the root itself')
    if '\\' in value:
        _fail('BUILD_ATOMIC_PATH_NOT_CANONICAL', f'{name} must use "/" separators: {value!r}')
    if value.startswith('/'):
        _fail('BUILD_ATOMIC_PATH_ABSOLUTE', f'{name} must be relative: {value!r}')
    if value.endswith('/') or '//' in value:
        _fail('BUILD_ATOMIC_PATH_NOT_CANONICAL', f'{name} has an empty segment: {value!r}')
    if any(segment in ('.', '..') for segment in value.split('/')):
        _fail('BUILD_ATOMIC_PATH_NOT_CANONICAL', f'{name} must not contain "." or "..": {value!r}')
    return value


def _require_id(value: object, name: str) -> str:
    if type(value) is not str or _ID_PATTERN.fullmatch(value) is None:
        _fail('BUILD_ATOMIC_ID_INVALID', f'{name} must be 32 lowercase hex characters')
    return value


def _require_digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        _fail('BUILD_ATOMIC_DIGEST_INVALID', f'{name} must be a lowercase SHA-256 digest')
    return value


def _require_size(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        _fail('BUILD_ATOMIC_SIZE_INVALID', f'{name} must be an exact non-negative integer')
    return value


def _safe_join(root: object, relative: str, label: str) -> Path:
    """Join through PathGuard and translate its rejection into a clear code."""

    try:
        return PathGuard.safe_join(root, relative)
    except PathGuard.PathViolation as error:
        _fail('BUILD_ATOMIC_PATH_UNSAFE', f'{label}: {error}')
    except OSError as error:
        _fail('BUILD_ATOMIC_IO_FAILED', f'{label}: {error}')


def _is_reparse(stat_result: os.stat_result) -> bool:
    if stat.S_ISLNK(stat_result.st_mode):
        return True
    return bool(getattr(stat_result, 'st_file_attributes', 0) & _REPARSE_FLAG)


def _lstat_or_none(path: object) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as error:
        _fail('BUILD_ATOMIC_LSTAT_FAILED', f'could not inspect {path}: {error}')


def _validate_regular_stat(stat_result: os.stat_result, label: str) -> None:
    if _is_reparse(stat_result):
        _fail('BUILD_ATOMIC_REPARSE_POINT', f'{label} must not be a symlink or junction')
    if not stat.S_ISREG(stat_result.st_mode):
        _fail('BUILD_ATOMIC_NOT_REGULAR', f'{label} must be a regular file')
    if getattr(stat_result, 'st_nlink', 1) != 1:
        _fail('BUILD_ATOMIC_HARDLINK', f'{label} must be a single unlinked file')


def _require_regular(
    path: object, label: str, *, missing_ok: bool = False
) -> os.stat_result | None:
    stat_result = _lstat_or_none(path)
    if stat_result is None:
        if missing_ok:
            return None
        _fail('BUILD_ATOMIC_EVIDENCE_MISSING', f'{label} does not exist: {path}')
    _validate_regular_stat(stat_result, label)
    return stat_result


def _require_directory(path: object, label: str) -> os.stat_result:
    stat_result = _lstat_or_none(path)
    if stat_result is None:
        _fail('BUILD_ATOMIC_DIRECTORY_MISSING', f'{label} does not exist: {path}')
    if _is_reparse(stat_result):
        _fail('BUILD_ATOMIC_REPARSE_POINT', f'{label} must not be a symlink or junction')
    if not stat.S_ISDIR(stat_result.st_mode):
        _fail('BUILD_ATOMIC_NOT_DIRECTORY', f'{label} must be a directory')
    return stat_result


def _stat_signature(stat_result: os.stat_result) -> tuple[object, ...]:
    return (
        getattr(stat_result, 'st_dev', None),
        getattr(stat_result, 'st_ino', None),
        getattr(stat_result, 'st_mode', None),
        getattr(stat_result, 'st_size', None),
        getattr(stat_result, 'st_mtime_ns', None),
        getattr(stat_result, 'st_ctime_ns', None),
        getattr(stat_result, 'st_nlink', None),
    )


def _identity(stat_result: os.stat_result) -> tuple[object, object]:
    return getattr(stat_result, 'st_dev', None), getattr(stat_result, 'st_ino', None)


def _read_json_bytes(path: Path, label: str) -> bytes:
    """Read one bounded regular JSON file and reject concurrent changes."""

    before = _require_regular(path, label)
    assert before is not None
    if before.st_size > _MAX_JSON_BYTES:
        _fail('BUILD_ATOMIC_JSON_TOO_LARGE', f'{label} exceeds {_MAX_JSON_BYTES} bytes')
    try:
        with open(path, 'rb') as handle:
            opened = os.fstat(handle.fileno())
            _validate_regular_stat(opened, label)
            if _identity(before) != _identity(opened):
                _fail('BUILD_ATOMIC_FILE_CHANGED', f'{label} changed while being opened')
            data = handle.read(_MAX_JSON_BYTES + 1)
            finished = os.fstat(handle.fileno())
    except ValueError:
        raise
    except OSError as error:
        _fail('BUILD_ATOMIC_READ_FAILED', f'could not read {label}: {error}')
    if len(data) > _MAX_JSON_BYTES:
        _fail('BUILD_ATOMIC_JSON_TOO_LARGE', f'{label} exceeds {_MAX_JSON_BYTES} bytes')
    if _stat_signature(opened) != _stat_signature(finished) or len(data) != finished.st_size:
        _fail('BUILD_ATOMIC_FILE_CHANGED', f'{label} changed while being read')
    after = _require_regular(path, label)
    assert after is not None
    if _identity(after) != _identity(opened):
        _fail('BUILD_ATOMIC_FILE_CHANGED', f'{label} was replaced while being read')
    return data


def _hash_artifact(path: Path, label: str) -> tuple[str, int]:
    """Incrementally hash actual bytes, rejecting a changing/linked artifact."""

    before = _require_regular(path, label)
    assert before is not None
    digest = hashlib.sha256()
    total = 0
    try:
        with open(path, 'rb') as handle:
            opened = os.fstat(handle.fileno())
            _validate_regular_stat(opened, label)
            if _identity(before) != _identity(opened):
                _fail('BUILD_ATOMIC_FILE_CHANGED', f'{label} changed while being opened')
            while True:
                block = handle.read(_READ_BLOCK)
                if not block:
                    break
                digest.update(block)
                total += len(block)
            finished = os.fstat(handle.fileno())
    except ValueError:
        raise
    except OSError as error:
        _fail('BUILD_ATOMIC_READ_FAILED', f'could not hash {label}: {error}')
    if _stat_signature(opened) != _stat_signature(finished) or total != finished.st_size:
        _fail('BUILD_ATOMIC_FILE_CHANGED', f'{label} changed while being hashed')
    after = _require_regular(path, label)
    assert after is not None
    if _identity(after) != _identity(opened):
        _fail('BUILD_ATOMIC_FILE_CHANGED', f'{label} was replaced while being hashed')
    return digest.hexdigest(), total


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key!r}')
        result[key] = value
    return result


def _json_constant(name: str):
    raise ValueError(f'non-finite JSON constant: {name}')


def _assert_json_finite(value: object, label: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _fail('BUILD_ATOMIC_JSON_NONFINITE', f'{label} contains a non-finite number')
    if isinstance(value, list):
        for item in value:
            _assert_json_finite(item, label)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_json_finite(item, label)


def _strict_json_loads(data: bytes, label: str) -> object:
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as error:
        _fail('BUILD_ATOMIC_JSON_INVALID', f'{label} is not valid UTF-8: {error}')
    try:
        value = json.loads(
            text,
            object_pairs_hook=_json_pairs,
            parse_constant=_json_constant,
        )
    except RecursionError as error:
        _fail('BUILD_ATOMIC_JSON_INVALID', f'{label} is nested too deeply: {error}')
    except (TypeError, ValueError) as error:
        _fail('BUILD_ATOMIC_JSON_INVALID', f'{label} is not valid JSON: {error}')
    try:
        _assert_json_finite(value, label)
    except RecursionError as error:
        _fail('BUILD_ATOMIC_JSON_INVALID', f'{label} is nested too deeply: {error}')
    return value


def _dump_json(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(',', ':'),
        )
    except (TypeError, ValueError) as error:
        _fail('BUILD_ATOMIC_JSON_INVALID', f'could not encode JSON: {error}')
    encoded = text.encode('utf-8')
    if len(encoded) > _MAX_JSON_BYTES:
        _fail('BUILD_ATOMIC_JSON_TOO_LARGE', f'encoded metadata exceeds {_MAX_JSON_BYTES} bytes')
    return encoded


def _temporary_relative(target: str, write_id: str) -> str:
    parent, separator, name = target.rpartition('/')
    temporary_name = f'.{name}.{write_id}.staging'
    return f'{parent}/{temporary_name}' if separator else temporary_name


class BuildAtomicWriter:
    """Write and recover output stages registered against one build journal.

    Callers must hold the project lock/job lease that owns ``attempt_id``.  The
    object does not take locks itself and never changes journal state.
    """

    def __init__(self, journal: object, attempt_id: str, allowed_paths: object) -> None:
        self._journal = journal
        try:
            project_root = journal.project_root
            records_root = journal.records_root
            staging = journal.staging
            build_id = journal.build_id
            descriptor = journal.descriptor
        except AttributeError as error:
            _fail('BUILD_ATOMIC_JOURNAL_INVALID', f'journal is missing a required property: {error}')
        self._project_root = Path(os.path.abspath(_path_text(project_root, 'journal.project_root')))
        self._records_root = Path(os.path.abspath(_path_text(records_root, 'journal.records_root')))
        self._staging = Path(os.path.abspath(_path_text(staging, 'journal.staging')))
        self._build_id = _require_id(build_id, 'journal.build_id')
        if not isinstance(descriptor, dict):
            _fail('BUILD_ATOMIC_DESCRIPTOR_INVALID', 'journal.descriptor must be a mapping')
        self._descriptor = dict(descriptor)
        self._plan_digest = _require_digest(descriptor.get('plan_digest'), 'descriptor.plan_digest')
        self._frozen_sha256 = _require_digest(
            descriptor.get('frozen_sha256'), 'descriptor.frozen_sha256'
        )

        attempt = _require_id(attempt_id, 'attempt_id')
        try:
            creator = journal.attempt(attempt)
        except Exception as error:
            _fail('BUILD_ATOMIC_ATTEMPT_UNKNOWN', f'unknown attempt_id {attempt}: {error}')
        if not isinstance(creator, dict) or creator.get('attempt_id') != attempt:
            _fail('BUILD_ATOMIC_ATTEMPT_UNKNOWN', f'journal returned no record for {attempt}')
        if creator.get('state') != 'RUNNING':
            _fail('BUILD_ATOMIC_ATTEMPT_NOT_RUNNING', f'attempt {attempt} is not RUNNING')
        self._attempt_id = attempt

        if isinstance(allowed_paths, (str, bytes, bytearray)):
            _fail(
                'BUILD_ATOMIC_ALLOWED_PATHS_INVALID',
                'allowed_paths must be an iterable of relative paths, not a string',
            )
        try:
            iterator = iter(allowed_paths)  # type: ignore[arg-type]
        except TypeError as error:
            _fail('BUILD_ATOMIC_ALLOWED_PATHS_INVALID', f'allowed_paths is not iterable: {error}')
        allowed = {}
        for value in iterator:
            relative = _canonical_relative(value, 'allowed_paths entry')
            target = _safe_join(self._staging, relative, f'allowed path {relative!r}')
            self._assert_target_lineage(relative, f'allowed path {relative!r}')
            target_stat = _lstat_or_none(target)
            if target_stat is not None and not stat.S_ISREG(target_stat.st_mode):
                _fail(
                    'BUILD_ATOMIC_ALLOWED_PATH_NOT_REGULAR',
                    f'allowed path names an existing non-regular file: {relative!r}',
                )
            key = relative.casefold()
            if key in allowed:
                if allowed[key] == relative:
                    _fail(
                        'BUILD_ATOMIC_ALLOWED_PATH_DUPLICATE',
                        f'duplicate allowed path: {relative!r}',
                    )
                _fail(
                    'BUILD_ATOMIC_ALLOWED_PATH_CASE_ALIAS',
                    f'allowed paths collide case-insensitively: {allowed[key]!r} and {relative!r}',
                )
            allowed[key] = relative
        self._allowed_paths = frozenset(allowed.values())

    def _assert_target_lineage(self, relative: str, label: str) -> None:
        """Reject an existing non-directory component in a target's parent chain."""

        current = self._staging
        for segment in relative.split('/')[:-1]:
            current = current / segment
            stat_result = _lstat_or_none(current)
            if stat_result is None:
                break
            if _is_reparse(stat_result):
                _fail('BUILD_ATOMIC_REPARSE_POINT', f'{label} parent is a link: {current}')
            if not stat.S_ISDIR(stat_result.st_mode):
                _fail(
                    'BUILD_ATOMIC_PATH_PARENT_NOT_DIRECTORY',
                    f'{label} parent is not a directory: {current}',
                )

    # -- write -------------------------------------------------------------

    def write(self, path: object, data: object, overwrite: bool = False) -> None:
        """Register and atomically write one authorized staging file.

        Path and payload validation both complete before a marker is created.
        The marker is committed before the output staging file is opened.  Any
        later failure deliberately leaves the marker and temporary in place.
        """

        self._require_running_attempt()
        target_text = _path_text(path, 'path')
        if any(part in ('.', '..') for part in re.split(r'[/\\]', target_text)):
            _fail('BUILD_ATOMIC_TARGET_NOT_CANONICAL', 'target must not contain dot path segments')
        if not os.path.isabs(target_text):
            _fail('BUILD_ATOMIC_TARGET_NOT_ABSOLUTE', f'target must be absolute: {target_text!r}')
        target_abs = os.path.normpath(os.path.abspath(target_text))
        staging_abs = os.path.normpath(os.path.abspath(str(self._staging)))
        root_key = os.path.normcase(staging_abs)
        target_key = os.path.normcase(target_abs)
        prefix = root_key if root_key.endswith(os.sep) else root_key + os.sep
        if not target_key.startswith(prefix):
            _fail(
                'BUILD_ATOMIC_TARGET_OUTSIDE_STAGING',
                f'target must be inside exactly {self._staging}',
            )
        relative_os = target_abs[len(staging_abs):].lstrip('/\\')
        relative = relative_os.replace(os.sep, '/')
        target_relative = _canonical_relative(relative, 'target')
        target_path = _safe_join(self._staging, target_relative, 'target')
        self._assert_target_lineage(target_relative, 'target')
        target_stat = _lstat_or_none(target_path)
        if target_stat is not None and not stat.S_ISREG(target_stat.st_mode):
            _fail(
                'BUILD_ATOMIC_TARGET_NOT_REGULAR',
                f'target is an existing non-regular file: {target_path}',
            )
        if target_relative not in self._allowed_paths:
            _fail(
                'BUILD_ATOMIC_TARGET_NOT_ALLOWED',
                f'target is not in the frozen allowed path set: {target_relative!r}',
            )

        if isinstance(data, (bytearray, memoryview)):
            payload = bytes(data)
        elif isinstance(data, bytes):
            payload = data
        else:
            _fail(
                'BUILD_ATOMIC_DATA_INVALID',
                f'write expects bytes, got {type(data).__name__}',
            )

        write_id = _require_id(uuid.uuid4().hex, 'write_id')
        temporary = _temporary_relative(target_relative, write_id)
        marker_path = _safe_join(
            self._records_root, f'{_ATOMIC_WRITES}/{write_id}.json', 'registration marker'
        )
        marker = {
            'schema_version': _SCHEMA_VERSION,
            'build_id': self._build_id,
            'attempt_id': self._attempt_id,
            'write_id': write_id,
            'plan_digest': self._plan_digest,
            'frozen_sha256': self._frozen_sha256,
            'target': target_relative,
            'temporary': temporary,
            'payload_sha256': hashlib.sha256(payload).hexdigest(),
            'payload_size': len(payload),
        }
        marker_bytes = _dump_json(marker)
        PathGuard.atomic_write(marker_path, marker_bytes)
        PathGuard.atomic_write(path, payload, overwrite, staging_id=write_id)

    # -- recovery ----------------------------------------------------------

    def recover(self) -> list[str]:
        """Validate every registration, then retain each recoverable stage.

        Marker validation is completed for the whole directory before the first
        proof is committed or the first rename occurs.  The return value uses
        project-relative ``builds/<build_id>/atomic-retained/<write_id>.bin``
        paths so it can be passed to the existing BuildService recovery list.
        """

        self._require_running_attempt()
        registrations = self._registrations()
        self._assert_no_orphan_evidence(registrations)
        plans = [self._preflight(registration) for registration in registrations]
        retained: list[str] = []
        for plan in plans:
            if plan['kind'] == 'none':
                continue
            self._require_running_attempt()
            if plan['kind'] == 'archived':
                self._verify_archived(plan)
            else:
                self._move_and_retain(plan)
            retained.append(plan['paths']['retained'])
        return retained

    def _require_running_attempt(self) -> None:
        try:
            attempt = self._journal.attempt(self._attempt_id)
        except Exception as error:
            _fail('BUILD_ATOMIC_ATTEMPT_UNKNOWN', f'could not read attempt: {error}')
        if not isinstance(attempt, dict) or attempt.get('state') != 'RUNNING':
            _fail(
                'BUILD_ATOMIC_ATTEMPT_NOT_RUNNING',
                f'attempt {self._attempt_id} is no longer RUNNING',
            )

    def _registrations(self) -> list[dict]:
        marker_directory = _safe_join(
            self._records_root, _ATOMIC_WRITES, 'registration marker directory'
        )
        directory_stat = _lstat_or_none(marker_directory)
        if directory_stat is None:
            return []
        if _is_reparse(directory_stat):
            _fail('BUILD_ATOMIC_REPARSE_POINT', 'marker directory is a symlink or junction')
        if not stat.S_ISDIR(directory_stat.st_mode):
            _fail('BUILD_ATOMIC_NOT_DIRECTORY', 'marker directory is not a directory')
        try:
            names = [
                entry.name
                for entry in os.scandir(marker_directory)
                if _FINAL_MARKER_PATTERN.fullmatch(entry.name) is not None
            ]
        except OSError as error:
            _fail('BUILD_ATOMIC_READ_FAILED', f'could not scan registration markers: {error}')
        registrations = []
        for name in sorted(names):
            marker_path = _safe_join(
                marker_directory, name, f'registration marker {name!r}'
            )
            raw = _read_json_bytes(marker_path, f'registration marker {name!r}')
            registrations.append(self._parse_marker(raw, name))
        return registrations

    def _assert_no_orphan_evidence(self, registrations: list[dict]) -> None:
        """Refuse final archive/proof files that have no valid registration."""

        registered = {registration['write_id'] for registration in registrations}
        for directory_name, pattern, suffix, label in (
            (_ATOMIC_RETAINED, _FINAL_ARCHIVE_PATTERN, '.bin', 'retained archive'),
            (_ATOMIC_RECOVERY, _FINAL_MARKER_PATTERN, '.json', 'recovery proof'),
        ):
            directory = _safe_join(self._records_root, directory_name, f'{label} directory')
            directory_stat = _lstat_or_none(directory)
            if directory_stat is None:
                continue
            if _is_reparse(directory_stat):
                _fail('BUILD_ATOMIC_REPARSE_POINT', f'{label} directory is a link')
            if not stat.S_ISDIR(directory_stat.st_mode):
                _fail('BUILD_ATOMIC_NOT_DIRECTORY', f'{label} directory is not a directory')
            try:
                names = [
                    entry.name
                    for entry in os.scandir(directory)
                    if pattern.fullmatch(entry.name) is not None
                ]
            except OSError as error:
                _fail('BUILD_ATOMIC_READ_FAILED', f'could not scan {label} files: {error}')
            for name in names:
                evidence_id = name[: -len(suffix)]
                if evidence_id not in registered:
                    _fail(
                        'BUILD_ATOMIC_ORPHAN_EVIDENCE',
                        f'{label} {name!r} has no valid registration marker',
                    )

    def _parse_marker(self, raw: bytes, filename: str) -> dict:
        label = f'registration marker {filename!r}'
        document = _strict_json_loads(raw, label)
        if type(document) is not dict:
            _fail('BUILD_ATOMIC_MARKER_INVALID', f'{label} must be a JSON object')
        if set(document) != _MARKER_KEYS:
            missing = sorted(_MARKER_KEYS - set(document))
            unknown = sorted(str(key) for key in set(document) - _MARKER_KEYS)
            _fail(
                'BUILD_ATOMIC_MARKER_KEYS',
                f'{label} keys must be exact; missing={missing} unknown={unknown}',
            )
        if type(document['schema_version']) is not int or document['schema_version'] != 1:
            _fail('BUILD_ATOMIC_MARKER_SCHEMA', f'{label} schema_version must be integer 1')
        marker_build_id = _require_id(document['build_id'], 'marker.build_id')
        if marker_build_id != self._build_id:
            _fail('BUILD_ATOMIC_MARKER_BUILD_MISMATCH', f'{label} belongs to another build')
        attempt_id = _require_id(document['attempt_id'], 'marker.attempt_id')
        write_id = _require_id(document['write_id'], 'marker.write_id')
        if filename != f'{write_id}.json':
            _fail('BUILD_ATOMIC_MARKER_NAME_MISMATCH', f'{label} does not match write_id')
        if _require_digest(document['plan_digest'], 'marker.plan_digest') != self._plan_digest:
            _fail('BUILD_ATOMIC_MARKER_PLAN_MISMATCH', f'{label} plan digest does not match')
        if (
            _require_digest(document['frozen_sha256'], 'marker.frozen_sha256')
            != self._frozen_sha256
        ):
            _fail('BUILD_ATOMIC_MARKER_FROZEN_MISMATCH', f'{label} frozen digest does not match')
        _require_digest(document['payload_sha256'], 'marker.payload_sha256')
        _require_size(document['payload_size'], 'marker.payload_size')

        target = _canonical_relative(document['target'], 'marker.target')
        target_path = _safe_join(self._staging, target, f'{label} target')
        target_stat = _lstat_or_none(target_path)
        if target_stat is not None and not stat.S_ISREG(target_stat.st_mode):
            _fail('BUILD_ATOMIC_TARGET_NOT_REGULAR', f'{label} target is not a regular file')
        if target not in self._allowed_paths:
            _fail('BUILD_ATOMIC_MARKER_TARGET_NOT_ALLOWED', f'{label} target is not allowed')
        temporary = _canonical_relative(document['temporary'], 'marker.temporary')
        if temporary != _temporary_relative(target, write_id):
            _fail(
                'BUILD_ATOMIC_MARKER_TEMPORARY_MISMATCH',
                f'{label} temporary is not the derived sibling stage',
            )
        _safe_join(self._staging, temporary, f'{label} temporary')

        try:
            creator = self._journal.attempt(attempt_id)
        except Exception as error:
            _fail(
                'BUILD_ATOMIC_CREATOR_ATTEMPT_INVALID',
                f'{label} creator attempt is absent: {error}',
            )
        if not isinstance(creator, dict) or creator.get('attempt_id') != attempt_id:
            _fail('BUILD_ATOMIC_CREATOR_ATTEMPT_INVALID', f'{label} creator attempt is absent')

        return {
            'write_id': write_id,
            'attempt_id': attempt_id,
            'target': target,
            'temporary': temporary,
            'marker_sha256': hashlib.sha256(raw).hexdigest(),
        }

    def _registration_paths(self, registration: dict) -> dict:
        write_id = registration['write_id']
        temporary = _safe_join(
            self._staging,
            registration['temporary'],
            f'registered temporary for {write_id}',
        )
        archive = _safe_join(
            self._records_root,
            f'{_ATOMIC_RETAINED}/{write_id}.bin',
            f'archive for {write_id}',
        )
        proof = _safe_join(
            self._records_root,
            f'{_ATOMIC_RECOVERY}/{write_id}.json',
            f'proof for {write_id}',
        )
        return {
            'temporary': temporary,
            'archive': archive,
            'proof': proof,
            'retained': f'builds/{self._build_id}/{_ATOMIC_RETAINED}/{write_id}.bin',
        }

    def _preflight(self, registration: dict) -> dict:
        """Check one registration's evidence without mutating anything."""

        paths = self._registration_paths(registration)
        temporary_stat = _require_regular(
            paths['temporary'], f"temporary {registration['write_id']}", missing_ok=True
        )
        archive_stat = _require_regular(
            paths['archive'], f"archive {registration['write_id']}", missing_ok=True
        )
        proof_stat = _require_regular(
            paths['proof'], f"proof {registration['write_id']}", missing_ok=True
        )
        if temporary_stat is None and archive_stat is None and proof_stat is None:
            return {'kind': 'none', 'registration': registration, 'paths': paths}
        if temporary_stat is not None and archive_stat is not None:
            _fail(
                'BUILD_ATOMIC_EVIDENCE_COLLISION',
                f"both temporary and archive exist for {registration['write_id']}",
            )
        if proof_stat is None:
            if archive_stat is not None:
                _fail(
                    'BUILD_ATOMIC_ARCHIVE_WITHOUT_PROOF',
                    f"archive exists without a proof for {registration['write_id']}",
                )
            return {'kind': 'move', 'registration': registration, 'paths': paths}

        proof = self._read_proof(registration, paths)
        if temporary_stat is not None:
            actual = _hash_artifact(paths['temporary'], 'registered temporary')
        elif archive_stat is not None:
            actual = _hash_artifact(paths['archive'], 'retained archive')
        else:
            _fail(
                'BUILD_ATOMIC_COMMITTED_EVIDENCE_MISSING',
                f"proof exists but temporary and archive are both missing for"
                f" {registration['write_id']}",
            )
        self._verify_proof_actual(proof, actual, registration)
        return {
            'kind': 'archived' if archive_stat is not None else 'move',
            'registration': registration,
            'paths': paths,
            'proof': proof,
            'actual': actual,
        }

    def _read_proof(self, registration: dict, paths: dict) -> dict:
        label = f"recovery proof {registration['write_id']}"
        raw = _read_json_bytes(paths['proof'], label)
        document = _strict_json_loads(raw, label)
        if type(document) is not dict:
            _fail('BUILD_ATOMIC_PROOF_INVALID', f'{label} must be a JSON object')
        if set(document) != _PROOF_KEYS:
            missing = sorted(_PROOF_KEYS - set(document))
            unknown = sorted(str(key) for key in set(document) - _PROOF_KEYS)
            _fail(
                'BUILD_ATOMIC_PROOF_KEYS',
                f'{label} keys must be exact; missing={missing} unknown={unknown}',
            )
        if type(document['schema_version']) is not int or document['schema_version'] != 1:
            _fail('BUILD_ATOMIC_PROOF_SCHEMA', f'{label} schema_version must be integer 1')
        if _require_id(document['build_id'], 'proof.build_id') != self._build_id:
            _fail('BUILD_ATOMIC_PROOF_BUILD_MISMATCH', f'{label} belongs to another build')
        if _require_id(document['write_id'], 'proof.write_id') != registration['write_id']:
            _fail('BUILD_ATOMIC_PROOF_WRITE_MISMATCH', f'{label} write_id does not match')
        marker_sha256 = _require_digest(document['marker_sha256'], 'proof.marker_sha256')
        if marker_sha256 != registration['marker_sha256']:
            _fail(
                'BUILD_ATOMIC_PROOF_MARKER_MISMATCH',
                f'{label} does not match the exact final marker bytes',
            )
        _require_digest(document['actual_sha256'], 'proof.actual_sha256')
        _require_size(document['actual_size'], 'proof.actual_size')
        return document

    def _verify_proof_actual(
        self, proof: dict, actual: tuple[str, int], registration: dict
    ) -> None:
        if proof['actual_sha256'] != actual[0] or proof['actual_size'] != actual[1]:
            _fail(
                'BUILD_ATOMIC_PROOF_ARTIFACT_MISMATCH',
                f"actual bytes do not match the committed proof for"
                f" {registration['write_id']}",
            )

    def _verify_archived(self, plan: dict) -> None:
        registration = plan['registration']
        paths = plan['paths']
        if _require_regular(paths['temporary'], 'registered temporary', missing_ok=True) is not None:
            _fail(
                'BUILD_ATOMIC_EVIDENCE_COLLISION',
                f"temporary reappeared beside archive {registration['write_id']}",
            )
        archive_stat = _require_regular(paths['archive'], 'retained archive')
        assert archive_stat is not None
        proof = self._read_proof(registration, paths)
        actual = _hash_artifact(paths['archive'], 'retained archive')
        self._verify_proof_actual(proof, actual, registration)

    def _move_and_retain(self, plan: dict) -> None:
        registration = plan['registration']
        paths = plan['paths']
        write_id = registration['write_id']
        temporary = paths['temporary']
        archive = paths['archive']
        proof_path = paths['proof']

        temporary_stat = _require_regular(temporary, 'registered temporary', missing_ok=True)
        if temporary_stat is None:
            _fail(
                'BUILD_ATOMIC_TEMPORARY_MISSING',
                f'registered temporary disappeared for {write_id}',
            )
        if _require_regular(archive, 'retained archive', missing_ok=True) is not None:
            _fail('BUILD_ATOMIC_EVIDENCE_COLLISION', f'archive already exists for {write_id}')

        actual = _hash_artifact(temporary, 'registered temporary')
        if _require_regular(proof_path, 'recovery proof', missing_ok=True) is None:
            self._commit_proof(registration, paths, actual)
        proof = self._read_proof(registration, paths)
        self._verify_proof_actual(proof, actual, registration)

        # Hash again immediately before the rename: a proof commits the exact
        # bytes, not merely a path name or a size field.
        current = _hash_artifact(temporary, 'registered temporary')
        if current != actual:
            _fail(
                'BUILD_ATOMIC_TEMPORARY_CHANGED',
                f'registered temporary changed after its proof was committed for {write_id}',
            )

        archive_directory = _safe_join(
            self._records_root, _ATOMIC_RETAINED, 'retained archive directory'
        )
        try:
            archive_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            _fail(
                'BUILD_ATOMIC_ARCHIVE_DIRECTORY_FAILED',
                f'could not create retained archive directory: {error}',
            )
        archive_directory_stat = _require_directory(
            archive_directory, 'retained archive directory'
        )
        source_stat = _require_regular(temporary, 'registered temporary')
        assert source_stat is not None
        if _identity(source_stat) != _identity(temporary_stat):
            _fail('BUILD_ATOMIC_TEMPORARY_CHANGED', f'temporary was replaced for {write_id}')
        if getattr(source_stat, 'st_dev', None) is None or getattr(
            archive_directory_stat, 'st_dev', None
        ) is None:
            _fail(
                'BUILD_ATOMIC_CROSS_DEVICE',
                f'cannot prove one filesystem for {write_id}; evidence was retained',
            )
        if source_stat.st_dev != archive_directory_stat.st_dev:
            _fail(
                'BUILD_ATOMIC_CROSS_DEVICE',
                f'temporary and retained archive directory are on different filesystems;'
                f' all evidence was retained for {write_id}',
            )
        if _require_regular(archive, 'retained archive', missing_ok=True) is not None:
            _fail('BUILD_ATOMIC_EVIDENCE_COLLISION', f'archive appeared for {write_id}')
        _safe_join(self._staging, registration['temporary'], 'source boundary')
        _safe_join(
            self._records_root, f'{_ATOMIC_RETAINED}/{write_id}.bin', 'archive boundary'
        )
        self._require_running_attempt()

        try:
            os.rename(temporary, archive)
        except FileExistsError as error:
            _fail(
                'BUILD_ATOMIC_EVIDENCE_COLLISION',
                f'an archive appeared during the move for {write_id}: {error}',
            )
        except OSError as error:
            if error.errno == errno.EXDEV:
                _fail(
                    'BUILD_ATOMIC_CROSS_DEVICE',
                    f'rename crossed filesystems; all evidence was retained for {write_id}',
                )
            if _lstat_or_none(archive) is not None:
                _fail(
                    'BUILD_ATOMIC_EVIDENCE_COLLISION',
                    f'an archive exists after the failed move for {write_id}: {error}',
                )
            raise

        _safe_join(self._staging, registration['temporary'], 'source boundary')
        if _lstat_or_none(temporary) is not None:
            _fail(
                'BUILD_ATOMIC_TEMPORARY_REAPPEARED',
                f'registered temporary still exists or reappeared for {write_id}',
            )
        _safe_join(
            self._records_root, f'{_ATOMIC_RETAINED}/{write_id}.bin', 'archive boundary'
        )
        archive_stat = _require_regular(archive, 'retained archive')
        assert archive_stat is not None
        archived = _hash_artifact(archive, 'retained archive')
        if archived != actual:
            _fail(
                'BUILD_ATOMIC_ARCHIVE_CHANGED',
                f'actual archive bytes changed during the move for {write_id}',
            )
        proof = self._read_proof(registration, paths)
        self._verify_proof_actual(proof, archived, registration)

    def _commit_proof(
        self, registration: dict, paths: dict, actual: tuple[str, int]
    ) -> dict:
        proof = {
            'schema_version': _SCHEMA_VERSION,
            'build_id': self._build_id,
            'write_id': registration['write_id'],
            'marker_sha256': registration['marker_sha256'],
            'actual_sha256': actual[0],
            'actual_size': actual[1],
        }
        proof_bytes = _dump_json(proof)
        try:
            PathGuard.atomic_write(paths['proof'], proof_bytes)
        except FileExistsError:
            # Immutable race loser: read and verify the existing proof instead.
            pass
        committed = self._read_proof(registration, paths)
        self._verify_proof_actual(committed, actual, registration)
        return committed
