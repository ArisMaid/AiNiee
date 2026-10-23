"""Path confinement helpers for RPG game project roots (contract v1).

Every helper is defensive and retains every file it creates: failed atomic
writes keep their uniquely named staging file so an operator can inspect it.
Paths are validated lexically *before* any resolution so reparse points
(symlinks and Windows junctions) are caught rather than silently followed.
"""

from __future__ import annotations

import os
import re
import stat
import time
import uuid
from pathlib import Path

__all__ = ['PathViolation', 'assert_disjoint', 'atomic_write', 'safe_join']

_DRIVE_PATTERN = re.compile(r'\A[A-Za-z]:')
_STAGING_ID_PATTERN = re.compile(r'[a-f0-9]{32}')
_REPARSE_FLAG = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
_OVERWRITE_RETRY_DELAYS = (0.03, 0.06, 0.12, 0.24, 0.48)
_WINDOWS_REPLACE_RETRY_WINERRORS = frozenset((5, 32, 33))
_WINDOWS_RESERVED_NAMES = frozenset(
    ['CON', 'PRN', 'AUX', 'NUL']
    + [f'COM{index}' for index in range(1, 10)]
    + [f'LPT{index}' for index in range(1, 10)]
)
_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*') | frozenset(chr(code) for code in range(32))


class PathViolation(ValueError):
    """Raised when a path would escape its root or is otherwise unsafe.

    A ``ValueError`` subtype carrying a stable machine readable :attr:`code`.
    """

    def __init__(self, code: str, message: str = '') -> None:
        self.code = str(code)
        super().__init__(str(message) or self.code)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _path_text(value: object, name: str) -> str:
    if isinstance(value, (bytes, bytearray)):
        raise PathViolation('invalid_path', f'{name} must be a string path, not bytes')
    try:
        text = os.fspath(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise PathViolation(
            'invalid_path', f'{name} must be a path-like value, got {type(value).__name__}'
        ) from error
    if isinstance(text, bytes):
        raise PathViolation('invalid_path', f'{name} must be a string path, not bytes')
    if text == '':
        raise PathViolation('empty_path', f'{name} must not be empty')
    if '\x00' in text:
        raise PathViolation('invalid_path', f'{name} must not contain NUL')
    return text


def _normalized_key(path: object, *, physical: bool = False) -> str:
    """Return a case-folded, separator-normalized key for path comparison."""

    text = os.path.abspath(_path_text(path, 'path'))
    if physical:
        text = os.path.realpath(text)
    text = os.path.normpath(text).replace('\\', '/')
    lowered = text.lower()
    if lowered.startswith('//?/unc/'):
        text = '//' + text[len('//?/unc/'):]
    elif lowered.startswith('//?/') or lowered.startswith('//./'):
        text = text[4:]
    key = text.casefold()
    if len(key) > 1:
        key = key.rstrip('/')
    return key or '/'


def _is_within(child: object, parent: object) -> bool:
    child_key = _normalized_key(child)
    parent_key = _normalized_key(parent)
    if parent_key == '/':
        return child_key.startswith('/')
    return child_key == parent_key or child_key.startswith(parent_key + '/')


def _overlaps(first: object, second: object) -> bool:
    """True when the two roots are equal or one contains the other."""

    for physical in (False, True):
        first_key = _normalized_key(first, physical=physical)
        second_key = _normalized_key(second, physical=physical)
        if first_key == second_key:
            return True
        if first_key == '/':
            return True
        if second_key == '/':
            return True
        if first_key.startswith(second_key + '/') or second_key.startswith(first_key + '/'):
            return True
    return False


def _validate_relative_segments(relative_path: object) -> tuple[str, ...]:
    text = _path_text(relative_path, 'relative_path')
    if text.startswith(('/', '\\')) or _DRIVE_PATTERN.match(text):
        raise PathViolation('absolute_path', f'relative_path must be relative: {text!r}')
    segments = text.replace('\\', '/').split('/')
    for segment in segments:
        if segment == '':
            raise PathViolation('empty_segment', f'relative_path has an empty segment: {text!r}')
        if segment == '.':
            raise PathViolation('unsafe_segment', f'relative_path has a "." segment: {text!r}')
        if segment == '..':
            raise PathViolation('traversal', f'relative_path escapes its root: {text!r}')
        if ':' in segment:
            raise PathViolation(
                'ads_not_allowed',
                f'relative_path has an alternate data stream or drive: {text!r}',
            )
        if any(char in _WINDOWS_INVALID_CHARS for char in segment):
            raise PathViolation(
                'invalid_character',
                f'relative_path has characters invalid on Windows: {text!r}',
            )
        if segment != segment.rstrip(' .'):
            raise PathViolation(
                'invalid_trailing_character',
                f'relative_path has a segment ending in a dot or space: {text!r}',
            )
        if segment.split('.')[0].upper() in _WINDOWS_RESERVED_NAMES:
            raise PathViolation(
                'reserved_device_name',
                f'relative_path uses a reserved Windows device name: {text!r}',
            )
    return tuple(segments)


def _lstat_or_none(path: Path) -> os.stat_result | None:
    """``os.lstat`` that only hides "does not exist" errors (fails closed)."""

    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None


def _is_reparse(stat_result: os.stat_result) -> bool:
    if stat.S_ISLNK(stat_result.st_mode):
        return True
    return bool(getattr(stat_result, 'st_file_attributes', 0) & _REPARSE_FLAG)


def _assert_no_reparse_below(root: Path, target: Path) -> None:
    """Inspect lexical parents below ``root`` before any resolution."""

    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise PathViolation('escaped_root', f'{target} is outside its root') from error
    current = root
    for part in relative.parts:
        current = current / part
        stat_result = _lstat_or_none(current)
        if stat_result is None:
            continue
        if _is_reparse(stat_result):
            raise PathViolation(
                'reparse_point', f'symlinks and junctions are not allowed: {current}'
            )


def _assert_not_hardlinked(target: Path) -> None:
    stat_result = _lstat_or_none(target)
    if stat_result is None or not stat.S_ISREG(stat_result.st_mode):
        return
    if getattr(stat_result, 'st_nlink', 1) > 1:
        raise PathViolation('hardlink_not_allowed', f'hard linked files are not allowed: {target}')


def _assert_overwrite_paths_safe(target: Path, staging: Path) -> None:
    """Re-check the target and the one staging file immediately before replace."""

    _assert_no_reparse_below(Path(target.anchor), target)
    _assert_no_reparse_below(Path(staging.anchor), staging)
    _assert_not_hardlinked(target)
    _assert_not_hardlinked(staging)


def _validated_staging_id(staging_id: object) -> str:
    """Require an externally preallocated staging id to be unambiguous."""

    if type(staging_id) is not str or _STAGING_ID_PATTERN.fullmatch(staging_id) is None:
        raise PathViolation(
            'staging_id_invalid',
            'staging_id must be exactly 32 lowercase hexadecimal characters',
        )
    return staging_id


def _replace_overwrite_with_retry(staging: Path, target: Path) -> None:
    """Replace ``target`` with the existing staging file, retrying Windows sharing errors."""

    for attempt in range(len(_OVERWRITE_RETRY_DELAYS) + 1):
        _assert_overwrite_paths_safe(target, staging)
        try:
            os.replace(staging, target)
            return
        except OSError as error:
            retry = (
                os.name == 'nt'
                and getattr(error, 'winerror', None) in _WINDOWS_REPLACE_RETRY_WINERRORS
                and attempt < len(_OVERWRITE_RETRY_DELAYS)
            )
            if not retry:
                raise
            time.sleep(_OVERWRITE_RETRY_DELAYS[attempt])


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def safe_join(root: object, relative_path: object, must_exist: bool = False) -> Path:
    """Join ``relative_path`` onto ``root`` and prove the result stays inside.

    Rejects absolute paths (including Windows drive and UNC forms on any OS),
    ``..`` traversal, alternate data streams, empty segments, reserved Windows
    device names, symlinks/junctions below ``root`` and hard linked files.  The
    returned path is absolute and normalized; because no reparse points below
    ``root`` are accepted, the lexical result is also the physical result.
    """

    root_text = _path_text(root, 'root')
    segments = _validate_relative_segments(relative_path)
    root_path = Path(os.path.abspath(root_text))
    _assert_no_reparse_below(Path(root_path.anchor), root_path)
    if os.path.exists(root_path):
        if not root_path.is_dir():
            raise PathViolation('root_not_directory', f'root is not a directory: {root_path}')
    target = Path(os.path.normpath(os.path.join(root_path, *segments)))
    _assert_no_reparse_below(root_path, target)
    if not _is_within(os.path.realpath(target), os.path.realpath(root_path)):
        raise PathViolation('escaped_root', f'{target} escapes its root {root_path}')
    if must_exist and not os.path.exists(target):
        raise PathViolation('not_found', f'path does not exist: {target}')
    _assert_not_hardlinked(target)
    return target


def assert_disjoint(*roots: object) -> None:
    """Reject roots that are equal or in an ancestor/descendant relationship.

    Comparison uses normalized, case-insensitive Windows semantics for both the
    lexical path and the physical path, so existing links and not-yet-created
    targets are both handled.
    """

    if len(roots) < 2:
        return
    texts = [_path_text(root, 'root') for root in roots]
    for first_index in range(len(texts)):
        for second_index in range(first_index + 1, len(texts)):
            first = texts[first_index]
            second = texts[second_index]
            if _overlaps(first, second):
                raise PathViolation(
                    'roots_overlap',
                    f'roots must be disjoint: {first!r} and {second!r} overlap',
                )


def atomic_write(
    path: object,
    data: bytes,
    overwrite: bool = False,
    *,
    staging_id: str | None = None,
) -> None:
    """Atomically write ``data`` to ``path`` through a uniquely named staging file.

    The target is refused by default when it already exists.  Parent directories
    are created when missing.  A failure after the staging file was created
    leaves that uniquely named file in place: this module never removes files
    and never performs cleanup.  ``staging_id`` may pin the staging name to a
    caller-allocated 32 character lowercase hex id; the id is validated before
    any directory or file is created.
    """

    target = Path(os.path.abspath(_path_text(path, 'path')))
    _assert_no_reparse_below(Path(target.anchor), target)
    _assert_not_hardlinked(target)
    stage_id = None
    if staging_id is not None:
        stage_id = _validated_staging_id(staging_id)
    if isinstance(data, (bytearray, memoryview)):
        payload = bytes(data)
    elif isinstance(data, bytes):
        payload = data
    else:
        raise PathViolation(
            'invalid_data', f'atomic_write expects bytes, got {type(data).__name__}'
        )
    if os.path.isdir(target):
        raise PathViolation('target_is_directory', f'target is a directory: {target}')
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    parent_stat = _lstat_or_none(parent)
    if parent_stat is not None and _is_reparse(parent_stat):
        raise PathViolation('reparse_point', f'parent is a symlink or junction: {parent}')
    if os.path.lexists(target) and not overwrite:
        raise FileExistsError(f'target already exists: {target}')
    if stage_id is None:
        stage_id = uuid.uuid4().hex
    staging = parent / f'.{target.name}.{stage_id}.staging'
    _assert_overwrite_paths_safe(target, staging)
    with open(staging, 'xb') as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if not overwrite and os.path.lexists(target):
        # Retain the staging file: another writer won the race.
        raise FileExistsError(f'target already exists: {target}')
    if overwrite:
        _replace_overwrite_with_retry(staging, target)
    elif os.name == 'nt':
        # Windows rename is atomic and refuses an existing destination, closing
        # the check/replace race. An unsuccessful staging file is retained.
        os.rename(staging, target)
    else:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, 'renameat2', None)
        if renameat2 is None:
            raise PathViolation('atomic_no_replace_unavailable', 'renameat2 support is required')
        if renameat2(-100, os.fsencode(staging), -100, os.fsencode(target), 1):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))
