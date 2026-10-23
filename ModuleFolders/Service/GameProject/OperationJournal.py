"""Ordered append-only SQLite checkpoint journal (contract v1)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import stat
from pathlib import Path

from ModuleFolders.Service.GameProject.PathGuard import PathViolation, safe_join

_SCHEMA_VERSION = 1
_MAX_ROWS = 128
_MAX_ROW_BYTES = 4 * 1024 * 1024
_MAX_BATCH_BYTES = 16 * 1024 * 1024
_DESCRIPTOR_KEYS = frozenset({'operation', 'algorithm', 'input_digest', 'item_count'})
_HEX = frozenset('0123456789abcdef')
_META = (('id', 'INTEGER'), ('schema_version', 'INTEGER'),
         ('descriptor_json', 'TEXT'), ('descriptor_digest', 'TEXT'))
_ITEMS = (('idx', 'INTEGER'), ('payload_json', 'TEXT'), ('digest', 'TEXT'))


class JournalError(ValueError):
    """Stable validation or corruption error for the operation journal."""
    def __init__(self, code, message=''):
        self.code = str(code)
        super().__init__(f'{self.code}: {message}' if message else self.code)

def _is_digest(value):
    return type(value) is str and len(value) == 64 and all(c in _HEX for c in value)

def _pairs(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('duplicate JSON key')
    return result

def _constant(value):
    raise ValueError(f'non-finite JSON constant: {value}')

def _validate_json(value, code):
    kind = type(value)
    if value is None or kind is bool or kind is str or kind is int:
        return
    if kind is float:
        if not math.isfinite(value):
            raise JournalError(code, 'NaN and Infinity are not valid JSON')
    elif kind is list:
        for item in value:
            _validate_json(item, code)
    elif kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise JournalError(code, 'JSON object keys must be strings')
            _validate_json(item, code)
    else:
        raise JournalError(code, f'unsupported JSON value: {kind.__name__}')

def _parse_json(text, code):
    if type(text) is not str:
        raise JournalError(code, 'stored JSON must be text')
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        _validate_json(value, code)
    except (TypeError, ValueError, RecursionError) as error:
        raise JournalError(code, 'malformed JSON') from error
    return value

def _canonical_json(value, code):
    try:
        _validate_json(value, code)
        text = json.dumps(value, allow_nan=False, ensure_ascii=False,
                          separators=(',', ':'), sort_keys=True)
        return text, text.encode('utf-8')
    except JournalError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise JournalError(code, 'value is not canonical JSON') from error

def _descriptor(value):
    if type(value) is not dict or set(value) != _DESCRIPTOR_KEYS:
        raise JournalError('JOURNAL_DESCRIPTOR_INVALID', 'descriptor keys are not exact')
    operation, algorithm = value['operation'], value['algorithm']
    input_digest, item_count = value['input_digest'], value['item_count']
    if (type(operation) is not str or not operation
            or type(algorithm) is not str or not algorithm):
        raise JournalError('JOURNAL_DESCRIPTOR_INVALID', 'operation/algorithm must be nonempty str')
    if not _is_digest(input_digest) or type(item_count) is not int or item_count < 0:
        raise JournalError('JOURNAL_DESCRIPTOR_INVALID', 'input_digest or item_count is invalid')
    record = {'algorithm': algorithm, 'input_digest': input_digest,
              'item_count': item_count, 'operation': operation}
    text, data = _canonical_json(record, 'JOURNAL_DESCRIPTOR_INVALID')
    return text, hashlib.sha256(data).hexdigest(), item_count

def _open_target(path):
    target = safe_join(path.parent, path.name)
    try:
        info = os.lstat(target)
    except (FileNotFoundError, NotADirectoryError) as error:
        raise FileNotFoundError(f'journal does not exist: {target}') from error
    if not stat.S_ISREG(info.st_mode):
        raise JournalError('JOURNAL_CORRUPT', 'journal is not a regular file')
    if getattr(info, 'st_nlink', 1) > 1:
        raise PathViolation('hardlink_not_allowed', f'hard linked files are not allowed: {target}')
    return safe_join(path.parent, path.name)

def _close(connection):
    try:
        connection.close()
    except sqlite3.Error:
        pass

def _connect(target, creating=False):
    connection = sqlite3.connect(target.as_uri() + '?mode=rw', uri=True, isolation_level=None)
    try:
        mode = connection.execute('PRAGMA journal_mode=DELETE' if creating else 'PRAGMA journal_mode').fetchone()
        if mode is None or str(mode[0]).lower() != 'delete':
            raise JournalError('JOURNAL_CORRUPT', 'journal_mode must be DELETE')
        connection.execute('PRAGMA synchronous=FULL')
    except BaseException:
        _close(connection)
        raise
    return connection

def _initialize(connection, descriptor_json, descriptor_digest):
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE journal_meta (id INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL, descriptor_json TEXT NOT NULL, descriptor_digest TEXT NOT NULL)')
        connection.execute('CREATE TABLE journal_items (idx INTEGER PRIMARY KEY, payload_json TEXT NOT NULL, digest TEXT NOT NULL)')
        connection.execute('INSERT INTO journal_meta (id, schema_version, descriptor_json, descriptor_digest) VALUES (1, ?, ?, ?)', (_SCHEMA_VERSION, descriptor_json, descriptor_digest))
        connection.execute('COMMIT')
    except BaseException:
        try:
            connection.execute('ROLLBACK')
        except sqlite3.Error:
            pass
        raise

def _check_schema(connection):
    objects = [(row[0], row[1]) for row in connection.execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' "
        'ORDER BY type, name')]
    if objects != [('table', 'journal_items'), ('table', 'journal_meta')]:
        raise JournalError('JOURNAL_CORRUPT', 'unexpected schema objects')
    meta = tuple((row[1], row[2].upper()) for row in connection.execute('PRAGMA table_info(journal_meta)'))
    items = tuple((row[1], row[2].upper()) for row in connection.execute('PRAGMA table_info(journal_items)'))
    if meta != _META or items != _ITEMS:
        raise JournalError('JOURNAL_CORRUPT', 'unexpected table columns')
    for table in ('journal_meta','journal_items'):
        columns=connection.execute('PRAGMA table_info('+table+')').fetchall()
        if any(row[4] is not None or row[5]!=(1 if index==0 else 0)
                or row[3]!=(0 if index==0 else 1) for index,row in enumerate(columns)):
            raise JournalError('JOURNAL_CORRUPT', 'unexpected column constraints')

def _row_digest(index, data):
    return hashlib.sha256(str(index).encode('ascii') + b'\n' + data).hexdigest()

def _verify(connection, expected_json, item_count):
    _check_schema(connection)
    meta = connection.execute(
        'SELECT id, schema_version, descriptor_json, descriptor_digest FROM journal_meta').fetchall()
    if len(meta) != 1:
        raise JournalError('JOURNAL_CORRUPT', 'journal metadata is missing or duplicated')
    identifier, version, stored_json, stored_digest = meta[0]
    if type(identifier) is not int or identifier != 1:
        raise JournalError('JOURNAL_CORRUPT', 'journal metadata marker is invalid')
    if type(version) is not int or version != _SCHEMA_VERSION:
        raise JournalError('JOURNAL_CORRUPT', 'journal schema version is unsupported')
    if type(stored_json) is not str or not _is_digest(stored_digest):
        raise JournalError('JOURNAL_CORRUPT', 'journal descriptor encoding is invalid')
    try:
        stored_bytes = stored_json.encode('utf-8')
    except UnicodeError as error:
        raise JournalError('JOURNAL_CORRUPT', 'journal descriptor is not UTF-8') from error
    if hashlib.sha256(stored_bytes).hexdigest() != stored_digest:
        raise JournalError('JOURNAL_CORRUPT', 'journal descriptor digest does not match')
    try:
        canonical_json, canonical_digest, _ = _descriptor(
            _parse_json(stored_json, 'JOURNAL_CORRUPT'))
    except JournalError as error:
        raise JournalError('JOURNAL_CORRUPT', 'journal descriptor is invalid') from error
    if canonical_json != stored_json or canonical_digest != stored_digest:
        raise JournalError('JOURNAL_CORRUPT', 'journal descriptor is not canonical')
    if stored_json != expected_json:
        raise JournalError('JOURNAL_INPUT_CHANGED', 'journal belongs to a different input')
    payloads, unit_ids, position = [], set(), 0
    for index, payload_json, digest in connection.execute(
            'SELECT idx, payload_json, digest FROM journal_items ORDER BY idx'):
        if (type(index) is not int or index != position or index < 0 or index >= item_count
                or type(payload_json) is not str or not _is_digest(digest)):
            raise JournalError('JOURNAL_CORRUPT', 'journal row indices or encoding are invalid')
        payload = _parse_json(payload_json, 'JOURNAL_CORRUPT')
        unit_id = payload.get('unit_id') if type(payload) is dict else None
        if type(unit_id) is not str or not unit_id or unit_id in unit_ids:
            raise JournalError('JOURNAL_CORRUPT', 'journal row payload or unit_id is invalid')
        unit_ids.add(unit_id)
        canonical_text, canonical_data = _canonical_json(payload, 'JOURNAL_CORRUPT')
        if (canonical_text != payload_json or len(canonical_data) > _MAX_ROW_BYTES
                or digest != _row_digest(index, canonical_data)):
            raise JournalError('JOURNAL_CORRUPT', 'journal row payload or digest is invalid')
        payloads.append(payload_json)
        position += 1
    return tuple(payloads), unit_ids

class OperationJournal:
    """Append-only ordered checkpoint journal; callers own the project lock."""
    def __init__(self, item_count, payloads, unit_ids, connection):
        self._item_count, self._payload_json = item_count, list(payloads)
        self._unit_ids, self._completed = set(unit_ids), len(payloads)
        self._connection = connection
    @classmethod
    def create(cls, path, descriptor):
        descriptor_json, descriptor_digest, item_count = _descriptor(descriptor)
        source = Path(path)
        target = safe_join(source.parent, source.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = safe_join(source.parent, source.name)
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, 'O_BINARY', 0)
        fd = os.open(target, flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_nlink', 1) > 1:
                raise PathViolation('unsafe_journal_file', f'unsafe journal file: {target}')
        finally:
            os.close(fd)
        target = safe_join(target.parent, target.name)
        connection = None
        try:
            connection = _connect(target, creating=True)
            _initialize(connection, descriptor_json, descriptor_digest)
        except BaseException as error:
            if connection is not None:
                _close(connection)
            if isinstance(error, sqlite3.Error):
                raise JournalError('JOURNAL_CORRUPT', 'journal creation failed') from error
            raise
        return cls(item_count, (), (), connection)
    @classmethod
    def open(cls, path, descriptor):
        descriptor_json, _, item_count = _descriptor(descriptor)
        target = _open_target(Path(path))
        connection = None
        try:
            connection = _connect(target)
            payloads, unit_ids = _verify(connection, descriptor_json, item_count)
        except BaseException as error:
            if connection is not None:
                _close(connection)
            if isinstance(error, sqlite3.Error):
                raise JournalError('JOURNAL_CORRUPT', 'journal cannot be read') from error
            raise
        return cls(item_count, payloads, unit_ids, connection)
    @property
    def completed(self): return self._completed
    def results(self): return tuple(_parse_json(text, 'JOURNAL_CORRUPT') for text in self._payload_json)
    def append(self, rows):
        connection = self._connection
        if connection is None:
            raise ValueError('journal is closed')
        if type(rows) is not list or not rows:
            raise JournalError('JOURNAL_ROWS_INVALID', 'rows must be a nonempty list of dicts')
        if len(rows) > _MAX_ROWS or self._completed + len(rows) > self._item_count:
            raise JournalError('JOURNAL_LIMIT_EXCEEDED', 'row count or item_count limit exceeded')
        prepared, seen, total_bytes = [], set(), 0
        for offset, row in enumerate(rows):
            unit_id = row.get('unit_id') if type(row) is dict else None
            if (type(unit_id) is not str or not unit_id
                    or unit_id in seen or unit_id in self._unit_ids):
                raise JournalError('JOURNAL_ROWS_INVALID', 'unit_id is missing, empty, or duplicated')
            seen.add(unit_id)
            text, data = _canonical_json(row, 'JOURNAL_ROWS_INVALID')
            total_bytes += len(data)
            if len(data) > _MAX_ROW_BYTES or total_bytes > _MAX_BATCH_BYTES:
                raise JournalError('JOURNAL_LIMIT_EXCEEDED', 'serialized row or batch exceeds its limit')
            index = self._completed + offset
            prepared.append((index, text, _row_digest(index, data)))
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.executemany(
                'INSERT INTO journal_items (idx, payload_json, digest) VALUES (?, ?, ?)', prepared)
            connection.execute('COMMIT')
        except BaseException as error:
            try:
                connection.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            self.close()
            if isinstance(error, sqlite3.Error):
                raise JournalError('JOURNAL_CORRUPT', 'journal append failed') from error
            raise
        self._completed += len(prepared)
        self._payload_json.extend(item[1] for item in prepared)
        self._unit_ids.update(seen)
    def close(self):
        connection, self._connection = self._connection, None
        if connection is not None: _close(connection)
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
