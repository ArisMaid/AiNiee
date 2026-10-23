"""Font coverage inspection and conservative Qt layout estimation.

Contract: ``docs/rpg/UI_QUALITY_CONTRACT.md``.

* :func:`inspect_font` is the only glyph evidence this tool produces.  It reads
  the font file, hashes it and compares the characters that must be rendered
  against every Unicode cmap subtable.  The font is never mutated and nothing
  is downloaded.
* :func:`measure_layout` is a *Qt estimate* produced with an existing
  ``QApplication``.  It is never a runtime or engine-side validation: the game
  is not executed and no pass is claimed.
"""

from __future__ import annotations

import contextlib
import hashlib
import math
import os
import unicodedata
from pathlib import Path

from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy

__all__ = ['inspect_font', 'measure_layout']

#: Unicode general categories that never render a glyph of their own.
_IGNORED_CATEGORIES = frozenset(('Cc', 'Cf'))
#: Chunk size used while hashing a font file.
_HASH_CHUNK = 1024 * 1024

_QT_ESTIMATE = 'qt-estimate'
_QT_UNVERIFIED = 'unverified-controls'


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _font_file(font_path: object) -> Path:
    """Return the supplied font path as a ``Path`` or raise ``ValueError``."""

    if isinstance(font_path, (bytes, bytearray)):
        raise ValueError('font_path must be a string path, not bytes')
    try:
        text = os.fspath(font_path)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(
            f'font_path must be a path-like value, got {type(font_path).__name__}'
        ) from error
    if isinstance(text, bytes):
        raise ValueError('font_path must be a string path, not bytes')
    if text == '':
        raise ValueError('font_path must not be empty')
    path = Path(text)
    if not path.is_file():
        raise ValueError(f'FONT_NOT_FOUND: {path}')
    return path


def _required_characters(texts: object) -> set:
    """Collect unique characters that must be rendered.

    Whitespace and the Unicode ``Cc``/``Cf`` categories are ignored because
    they never need a glyph of their own.
    """

    if isinstance(texts, str):
        values = (texts,)
    else:
        if isinstance(texts, (bytes, bytearray)):
            raise ValueError('texts must be a string or an iterable of strings')
        try:
            values = tuple(texts)  # type: ignore[arg-type]
        except TypeError as error:
            raise ValueError('texts must be a string or an iterable of strings') from error
    required: set = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f'texts must contain only strings, got {type(value).__name__}')
        for character in value:
            if character.isspace() or unicodedata.category(character) in _IGNORED_CATEGORIES:
                continue
            required.add(character)
    return required


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as handle:
            for block in iter(lambda: handle.read(_HASH_CHUNK), b''):
                digest.update(block)
    except OSError as error:
        raise ValueError(f'FONT_UNREADABLE: {path}: {error}') from error
    return digest.hexdigest()


def _unicode_codepoints(path: Path) -> set:
    """Return every code point covered by a Unicode cmap subtable of ``path``."""

    try:
        from fontTools.ttLib import TTFont
    except ImportError as error:  # fontTools is an optional runtime dependency
        raise ValueError('FONT_TOOLS_UNAVAILABLE: fontTools is required to inspect fonts') from error
    font = None
    try:
        try:
            font = TTFont(str(path), fontNumber=0)
            cmap = font.get('cmap')
            if cmap is None:
                raise ValueError(f'FONT_WITHOUT_CMAP: {path}')
            covered: set = set()
            for table in getattr(cmap, 'tables', ()):
                is_unicode = getattr(table, 'isUnicode', None)
                if callable(is_unicode) and not is_unicode():
                    continue
                mapping = getattr(table, 'cmap', None)
                if not isinstance(mapping, dict):
                    continue
                for code, glyph in mapping.items():
                    if glyph == '.notdef':
                        continue
                    if isinstance(code, int) and not isinstance(code, bool):
                        covered.add(code)
            return covered
        except ValueError:
            raise
        except Exception as error:  # fontTools errors, truncated files, bad sfnt data
            raise ValueError(f'FONT_UNREADABLE: {path}: {error}') from error
    finally:
        if font is not None:
            # A font handle is always released, even when parsing failed halfway.
            with contextlib.suppress(Exception):
                font.close()


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a number, got {type(value).__name__}')
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f'{name} must be a positive finite number, got {value!r}')
    return number


def _visible_text(text: str) -> tuple:
    """Strip RPG Maker backslash controls conservatively.

    ``TokenPolicy.scan`` supplies the recognised control and template spans.
    Only spans that start with a backslash are removed from the measured text;
    template placeholders such as ``{name}`` or ``%1`` stay visible because the
    engine prints them.  Every scanner finding is returned so the caller can
    downgrade the measurement instead of reporting a clean estimate.
    """

    policy = TokenPolicy()
    tokens, issues = policy.scan(text)
    pieces = []
    start = 0
    for token in tokens:
        if token.raw.startswith('\\'):
            pieces.append(text[start:token.start])
            start = token.end
    pieces.append(text[start:])
    return ''.join(pieces), tuple(issues)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def inspect_font(font_path, texts) -> dict:
    """Return JSON-safe glyph coverage evidence for ``texts``.

    The returned dictionary always contains ``font_path`` (the supplied path),
    ``sha256`` of the font file, ``character_count`` (unique inspected
    characters after the whitespace/``Cc``/``Cf`` filter), ``missing_count``,
    ``missing_characters`` (sorted unique list) and ``passed``.
    """

    path = _font_file(font_path)
    required = _required_characters(texts)
    digest = _file_sha256(path)
    covered = _unicode_codepoints(path)
    missing = sorted(character for character in required if ord(character) not in covered)
    return {
        'font_path': str(path),
        'sha256': digest,
        'character_count': len(required),
        'missing_count': len(missing),
        'missing_characters': missing,
        'passed': not missing,
    }


def measure_layout(text, *, width_px, font_family, pixel_size=28) -> dict:
    """Estimate the rendered width of ``text`` with Qt font metrics.

    The measurement requires an existing ``QApplication``; without one a
    ``RuntimeError`` is raised instead of guessing.  Explicit newlines are
    respected and ``overflow`` is true when any single line is wider than
    ``width_px``.  ``measurement`` is ``'qt-estimate'`` for text whose controls
    were fully recognised and ``'unverified-controls'`` when ``TokenPolicy``
    reported an unknown or malformed control, in which case the estimate must
    not be treated as a layout pass.
    """

    if not isinstance(text, str):
        raise ValueError(f'text must be a string, got {type(text).__name__}')
    width = _positive_number(width_px, 'width_px')
    size = _positive_number(pixel_size, 'pixel_size')
    if not isinstance(font_family, str) or font_family.strip() == '':
        raise ValueError('font_family must be a non empty string')

    try:
        from PyQt5.QtGui import QFont, QFontMetricsF
        from PyQt5.QtWidgets import QApplication
    except ImportError as error:
        raise RuntimeError('QT_UNAVAILABLE: PyQt5 is required for layout measurement') from error
    if QApplication.instance() is None:
        raise RuntimeError(
            'QT_APPLICATION_REQUIRED: an existing QApplication is required for layout measurement'
        )

    visible, issues = _visible_text(text)
    font = QFont(font_family)
    font.setPixelSize(max(1, int(round(size))))
    metrics = QFontMetricsF(font)

    lines = visible.replace('\r\n', '\n').replace('\r', '\n').split('\n') or ['']
    measured = max(float(metrics.horizontalAdvance(line)) for line in lines)
    return {
        'width_px': width,
        'measured_width': measured,
        'line_count': len(lines),
        'overflow': measured > width,
        'measurement': _QT_UNVERIFIED if issues else _QT_ESTIMATE,
    }
