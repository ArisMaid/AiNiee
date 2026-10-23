"""Deterministic PNG codec, text overlay renderer and Tesseract OCR bridge.

Contract: ``docs/rpg/IMAGE_CONTRACT.md`` (image processing v1).

Only PNG, RPG Maker MV ``.rpgmvp`` and RPG Maker MZ ``.png_`` are accepted;
every other suffix is rejected explicitly.  All public functions validate
their input and raise :class:`ImageCodecError`, a :class:`ValueError` subclass
whose message starts with a stable machine readable ``code``.

Deliberate boundaries of this module:

* The RPG Maker key is only read by :func:`decode_image` and
  :func:`encode_image`; it is never logged, printed or embedded in a message.
* Pillow global limits are never modified.  The codec enforces its own
  64 MiB input and 16,000,000 pixel budget instead.
* OCR output is evidence only.  No translation unit, adapter id or database
  write happens here, and the OCR copy (transparent input flattened on white)
  is never written back to disk.
* Tesseract uses an explicit argv and minimal environment. Windows workers
  belong to an owned Job before execution; pipe readers cap retained output
  and stop the tree on overflow, timeout or cancellation.
* Rendering never clears the base image, never shrinks or truncates text and
  never changes a pixel outside a requested box, alpha included.
"""

from __future__ import annotations

import contextlib
import math
import os
import re
import subprocess
from ModuleFolders.Infrastructure.Platform.OwnedProcess import run as run_owned_process,OutputLimitExceeded
import unicodedata
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

__all__ = ['ImageCodecError', 'decode_image', 'encode_image', 'ocr_png', 'render_png']

#: PNG file signature; the RPG Maker body is an ordinary PNG after decryption.
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
#: Fixed 16 byte RPG Maker MV/MZ encryption header (rmmz_core.js checkEncryptionHeader).
ENCRYPTED_HEADER = bytes.fromhex('5250474d560000000003010000000000')

#: Input image limit (bytes) and decrypted pixel limit.
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 16_000_000
#: Font file limit and overlay limits.
MAX_FONT_BYTES = 32 * 1024 * 1024
MAX_OVERLAYS = 500
MAX_TEXT_LENGTH = 2000
MIN_FONT_SIZE = 6
MAX_FONT_SIZE = 256
#: Tesseract limits.
MIN_OCR_TIMEOUT = 1
MAX_OCR_TIMEOUT = 120
OCR_OUTPUT_LIMIT = 8 * 1024 * 1024

_SUFFIX_ENCRYPTED = {'.png': False, '.rpgmvp': True, '.png_': True}
_SFNT_VERSIONS = (b'\x00\x01\x00\x00', b'OTTO', b'true')
_KEY_PATTERN = re.compile(r'\A[0-9a-fA-F]{32}\Z')
_LANGUAGE_PATTERN = re.compile(r'\A[a-z_]+\Z')
_ALIGNMENTS = ('left', 'center', 'right')
_WORD_LEVEL = 5
#: Columns the parser needs; the standard Tesseract TSV header also carries
#: page_num and word_num, which are not required by this grouping.
_TSV_FIELDS = (
    'level', 'block_num', 'par_num', 'line_num',
    'left', 'top', 'width', 'height', 'conf', 'text',
)


# ---------------------------------------------------------------------------
# error handling
# ---------------------------------------------------------------------------

class ImageCodecError(ValueError):
    """Rejected image input, carrying a stable machine readable ``code``.

    The message starts with :attr:`code`, so callers may match either
    ``str(error)`` or ``error.code``.  The message never contains the RPG
    Maker key, font bytes, OCR text or process environment contents.
    """

    def __init__(self, code: str, detail: str = '') -> None:
        self.code = str(code)
        super().__init__(f'{self.code}: {detail}' if detail else self.code)


def _error(code: str, detail: str = '') -> ImageCodecError:
    return ImageCodecError(code, detail)


# ---------------------------------------------------------------------------
# shared validation helpers
# ---------------------------------------------------------------------------

def _input_bytes(data: object, label: str) -> bytes:
    """Return ``data`` as bytes or reject it (exact type, non empty, sized)."""

    if not isinstance(data, bytes):
        raise _error('IMAGE_NOT_BYTES', f'{label} must be bytes, got {type(data).__name__}')
    if len(data) == 0:
        raise _error('IMAGE_EMPTY', f'{label} must not be empty')
    if len(data) > MAX_INPUT_BYTES:
        raise _error(
            'IMAGE_TOO_LARGE',
            f'{label} has {len(data)} bytes; the limit is {MAX_INPUT_BYTES}',
        )
    return data


def _encryption(suffix: object) -> bool:
    """Return True when ``suffix`` names an encrypted RPG Maker container."""

    if not isinstance(suffix, str):
        raise _error(
            'IMAGE_SUFFIX_INVALID', f'suffix must be a string, got {type(suffix).__name__}'
        )
    try:
        return _SUFFIX_ENCRYPTED[suffix.lower()]
    except KeyError:
        raise _error('IMAGE_UNSUPPORTED_SUFFIX', f'unsupported image suffix: {suffix!r}') from None


def _key_bytes(key: object) -> bytes:
    """Validate the 32 hexadecimal digit key and return its 16 bytes.

    The value is never logged; the only trace of a bad key is the stable code.
    """

    if not isinstance(key, str) or _KEY_PATTERN.match(key) is None:
        raise _error('IMAGE_KEY_INVALID', 'key must be exactly 32 hexadecimal characters')
    return bytes.fromhex(key)


def _open_png(data: object, label: str = 'data') -> Image.Image:
    """Validate and fully decode a PNG, enforcing every structural limit."""

    raw = _input_bytes(data, label)
    if not raw.startswith(PNG_SIGNATURE):
        raise _error('IMAGE_NOT_PNG', f'{label} does not start with the PNG signature')
    try:
        image = Image.open(BytesIO(raw), formats=['PNG'])
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        # Pillow's own bomb guard (a warning only when warnings are errors).
        raise _error('IMAGE_PIXEL_LIMIT', f'{label} exceeds the pixel budget') from error
    except Exception as error:  # unreadable container: bad signature/IHDR/CRC
        raise _error('IMAGE_CORRUPT', f'{label} is not a readable PNG file') from error
    try:
        if image.format != 'PNG':
            raise _error('IMAGE_NOT_PNG', f'{label} is not a PNG file (detected {image.format})')
        width, height = image.size
        if width < 1 or height < 1:
            raise _error(
                'IMAGE_DIMENSIONS_INVALID', f'{label} has invalid dimensions {width}x{height}'
            )
        if width * height > MAX_PIXELS:
            raise _error(
                'IMAGE_PIXEL_LIMIT',
                f'{label} has {width * height} pixels; the limit is {MAX_PIXELS}',
            )
        frames = getattr(image, 'n_frames', 1)
        if getattr(image, 'is_animated', False) or frames != 1:
            raise _error('IMAGE_ANIMATED', f'{label} is animated ({frames} frames)')
        image.load()  # decodes every IDAT chunk: truncation and corruption surface here
        # Pixel decoding alone does not verify IDAT CRCs in Pillow.
        with Image.open(BytesIO(raw), formats=['PNG']) as integrity:
            integrity.verify()
    except ImageCodecError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise _error('IMAGE_PIXEL_LIMIT', f'{label} exceeds the pixel budget') from error
    except Exception as error:
        raise _error(
            'IMAGE_CORRUPT', f'{label} could not be decoded: {type(error).__name__}'
        ) from error
    return image


# ---------------------------------------------------------------------------
# decode / encode
# ---------------------------------------------------------------------------

def decode_image(data: bytes, suffix: str, key: str = '') -> tuple[bytes, dict]:
    """Return the plain PNG bytes of ``data`` plus its structural information.

    Plain ``.png`` input is returned unchanged after validation, and a key
    given for a plain suffix is ignored because only the encrypted containers
    use it.  ``.rpgmvp`` (MV) and ``.png_`` (MZ) input must carry the exact 16
    byte header; the key must be 32 hexadecimal digits and is XORed over the
    first 16 body bytes, which is the algorithm the MV/MZ runtimes implement.
    The returned mapping holds ``width``, ``height``, ``mode`` and
    ``encrypted``.
    """

    raw = _input_bytes(data, 'data')
    encrypted = _encryption(suffix)
    if encrypted:
        if len(raw) < len(ENCRYPTED_HEADER) or raw[: len(ENCRYPTED_HEADER)] != ENCRYPTED_HEADER:
            raise _error(
                'IMAGE_HEADER_MISMATCH',
                'the 16 byte RPG Maker encryption header is not the expected value',
            )
        body = raw[len(ENCRYPTED_HEADER):]
        if len(body) < 16:
            raise _error(
                'IMAGE_ENCRYPTED_TRUNCATED', 'the encrypted body is shorter than one XOR block'
            )
        mask = _key_bytes(key)
        payload = bytes(value ^ mask[index] for index, value in enumerate(body[:16])) + body[16:]
    else:
        payload = raw
    image = _open_png(payload, 'data')
    return payload, {
        'width': image.width,
        'height': image.height,
        'mode': image.mode,
        'encrypted': encrypted,
    }


def encode_image(png: bytes, suffix: str, key: str = '') -> bytes:
    """Validate ``png`` and wrap it for ``suffix``.

    A plain ``.png`` suffix returns the validated bytes unchanged and ignores
    the key.  Encrypted suffixes prepend the fixed header and XOR the key over
    the first 16 bytes of the PNG body, reversing :func:`decode_image`.
    """

    raw = _input_bytes(png, 'png')
    _open_png(raw, 'png')
    if not _encryption(suffix):
        return raw
    mask = _key_bytes(key)
    return (
        ENCRYPTED_HEADER
        + bytes(value ^ mask[index] for index, value in enumerate(raw[:16]))
        + raw[16:]
    )


# ---------------------------------------------------------------------------
# overlay rendering
# ---------------------------------------------------------------------------

class _FontCatalog:
    """One validated TrueType/OpenType font, its cmap coverage and size cache."""

    def __init__(self, data: bytes, covered: set) -> None:
        self._data = data
        self.covered = covered
        self._fonts: dict = {}

    def at(self, size: int) -> ImageFont.FreeTypeFont:
        """Return the Pillow font for ``size``, loading it at most once."""

        font = self._fonts.get(size)
        if font is None:
            try:
                # A fresh buffer per size: Pillow reads the stream to its end.
                font = ImageFont.truetype(BytesIO(self._data), size=size)
            except Exception as error:
                raise _error(
                    'IMAGE_FONT_INVALID', f'Pillow could not load the font: {type(error).__name__}'
                ) from error
            self._fonts[size] = font
        return font


def _font_coverage(font_bytes: bytes) -> set:
    """Return every code point of a single TTF/OTF font that is not .notdef."""

    try:
        from fontTools.ttLib import TTFont
    except ImportError as error:  # pragma: no cover - dependency is part of the runtime
        raise _error(
            'IMAGE_FONT_TOOLS_UNAVAILABLE', 'fontTools is required to validate fonts'
        ) from error
    font = None
    try:
        font = TTFont(BytesIO(font_bytes), fontNumber=0, lazy=True)
        if getattr(font, 'flavor', None):
            raise _error('IMAGE_FONT_INVALID', 'compressed web fonts are not supported')
        cmap = font.get('cmap')
        if cmap is None:
            raise _error('IMAGE_FONT_CMAP_MISSING', 'the font has no cmap table')
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
    except ImageCodecError:
        raise
    except Exception as error:  # truncated sfnt directory, broken tables, TTC without index
        raise _error(
            'IMAGE_FONT_INVALID', f'fontTools could not parse the font: {type(error).__name__}'
        ) from error
    finally:
        if font is not None:
            # The handle is always released, even when parsing failed halfway.
            with contextlib.suppress(Exception):
                font.close()


def _load_font(font_bytes: object) -> _FontCatalog:
    """Validate ``font_bytes`` as one TrueType/OpenType font (TTC rejected)."""

    if not isinstance(font_bytes, bytes):
        raise _error(
            'IMAGE_FONT_NOT_BYTES', f'font_bytes must be bytes, got {type(font_bytes).__name__}'
        )
    if len(font_bytes) == 0:
        raise _error('IMAGE_FONT_EMPTY', 'font_bytes must not be empty')
    if len(font_bytes) > MAX_FONT_BYTES:
        raise _error(
            'IMAGE_FONT_TOO_LARGE',
            f'font_bytes has {len(font_bytes)} bytes; the limit is {MAX_FONT_BYTES}',
        )
    version = font_bytes[:4]
    if version == b'ttcf':
        raise _error('IMAGE_FONT_TTC_UNSUPPORTED', 'font collections (TTC) are not supported')
    if version not in _SFNT_VERSIONS:
        raise _error('IMAGE_FONT_INVALID', 'font_bytes is not a TrueType or OpenType font')
    catalog = _FontCatalog(font_bytes, _font_coverage(font_bytes))
    catalog.at(MIN_FONT_SIZE)  # forces one FreeType load so bad outlines fail here
    return catalog


def _overlay_int(value: object, where: str, minimum: int, maximum: int) -> int:
    """Exact integer check: booleans, floats and strings are rejected."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise _error('IMAGE_OVERLAY_INVALID', f'{where} must be an integer, got {type(value).__name__}')
    if value < minimum or value > maximum:
        raise _error(
            'IMAGE_OVERLAY_INVALID', f'{where} must be between {minimum} and {maximum}, got {value}'
        )
    return int(value)


def _parse_overlay(raw: object, index: int, width: int, height: int) -> dict:
    """Validate one overlay entry and normalise it for rendering."""

    where = f'overlays[{index}]'
    if not isinstance(raw, dict):
        raise _error('IMAGE_OVERLAY_INVALID', f'{where} must be an object, got {type(raw).__name__}')
    box = raw.get('box')
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise _error('IMAGE_OVERLAY_INVALID', f'{where}.box must be [x, y, w, h]')
    x = _overlay_int(box[0], f'{where}.box[0]', 0, width)
    y = _overlay_int(box[1], f'{where}.box[1]', 0, height)
    box_width = _overlay_int(box[2], f'{where}.box[2]', 1, width)
    box_height = _overlay_int(box[3], f'{where}.box[3]', 1, height)
    if x + box_width > width or y + box_height > height:
        raise _error(
            'IMAGE_OVERLAY_BOX_OUTSIDE',
            f'{where}.box is not completely inside the {width}x{height} image',
        )
    text = raw.get('text')
    if not isinstance(text, str):
        raise _error(
            'IMAGE_OVERLAY_INVALID', f'{where}.text must be a string, got {type(text).__name__}'
        )
    if len(text) > MAX_TEXT_LENGTH:
        raise _error(
            'IMAGE_OVERLAY_TEXT_TOO_LONG',
            f'{where}.text has {len(text)} characters; the limit is {MAX_TEXT_LENGTH}',
        )
    font_size = _overlay_int(
        raw.get('font_size'), f'{where}.font_size', MIN_FONT_SIZE, MAX_FONT_SIZE
    )
    color = raw.get('color')
    if not isinstance(color, (list, tuple)) or len(color) != 4:
        raise _error('IMAGE_OVERLAY_INVALID', f'{where}.color must be [r, g, b, a]')
    channels = tuple(
        _overlay_int(channel, f'{where}.color[{position}]', 0, 255)
        for position, channel in enumerate(color)
    )
    align = raw.get('align')
    if align not in _ALIGNMENTS:
        raise _error(
            'IMAGE_OVERLAY_INVALID', f'{where}.align must be one of {", ".join(_ALIGNMENTS)}'
        )
    return {
        'index': index,
        'box': (x, y, box_width, box_height),
        'text': text,
        'lines': text.replace('\r\n', '\n').replace('\r', '\n').split('\n'),
        'font_size': font_size,
        'color': channels,
        'align': align,
    }


def _boxes_overlap(first: tuple, second: tuple) -> bool:
    """True when two boxes share at least one pixel; touching edges are fine."""

    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    return (
        first_x < second_x + second_width
        and second_x < first_x + first_width
        and first_y < second_y + second_height
        and second_y < first_y + first_height
    )


def _parse_overlays(overlays: object, width: int, height: int) -> list:
    """Validate the overlay collection: list, count, per item and overlap."""

    if not isinstance(overlays, list):
        raise _error(
            'IMAGE_OVERLAYS_INVALID', f'overlays must be a list, got {type(overlays).__name__}'
        )
    if len(overlays) == 0:
        raise _error('IMAGE_OVERLAYS_EMPTY', 'overlays must not be empty')
    if len(overlays) > MAX_OVERLAYS:
        raise _error(
            'IMAGE_OVERLAY_LIMIT', f'overlays has {len(overlays)} items; the limit is {MAX_OVERLAYS}'
        )
    items = [_parse_overlay(raw, index, width, height) for index, raw in enumerate(overlays)]
    for first_index in range(len(items)):
        for second_index in range(first_index + 1, len(items)):
            if _boxes_overlap(items[first_index]['box'], items[second_index]['box']):
                raise _error(
                    'IMAGE_OVERLAY_BOX_OVERLAP',
                    f'overlays[{first_index}] and overlays[{second_index}] overlap',
                )
    return items


def _codepoints(characters: list, limit: int = 16) -> str:
    labels = [f'U+{ord(character):04X}' for character in characters[:limit]]
    if len(characters) > limit:
        labels.append(f'and {len(characters) - limit} more')
    return ', '.join(labels)


def _draw_overlay(output: Image.Image, item: dict, catalog: _FontCatalog) -> None:
    """Draw one overlay through a box sized layer, then composite that box.

    Every line is measured with :meth:`~PIL.ImageDraw.ImageDraw.textbbox`; the
    first line whose ink leaves the box aborts the whole render.  Because the
    composite is pasted back over exactly the box rectangle, pixels outside it
    keep their original value, alpha included.
    """

    x, y, box_width, box_height = item['box']
    font = catalog.at(item['font_size'])
    ascent, descent = font.getmetrics()
    line_height = ascent + abs(descent)
    if line_height <= 0:
        line_height = item['font_size']
    region = output.crop((x, y, x + box_width, y + box_height))
    layer = Image.new('RGBA', (box_width, box_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for position, line in enumerate(item['lines']):
        if line == '':  # an empty line has no ink and is not drawn
            continue
        top = int(round(position * line_height))
        length = draw.textlength(line, font=font)
        if item['align'] == 'left':
            left = 0.0
        elif item['align'] == 'center':
            left = (box_width - length) / 2.0
        else:
            left = box_width - length
        left = int(round(left))
        ink = draw.textbbox((left, top), line, font=font)
        if ink[0] < 0 or ink[1] < 0 or ink[2] > box_width or ink[3] > box_height:
            raise _error(
                'IMAGE_LAYOUT_OVERFLOW', f"overlays[{item['index']}] text leaves its box"
            )
        draw.text((left, top), line, font=font, fill=item['color'])
    output.paste(Image.alpha_composite(region, layer), (x, y))


def render_png(base_png: bytes, overlays: list, font_bytes: bytes) -> bytes:
    """Overlay confirmed text on a clean base image and return RGBA PNG bytes.

    The base image is never modified or cleared: text is composited on top of
    it.  Missing glyphs and any layout overflow are rejected before a single
    pixel is written.  The output keeps the base size and every pixel outside
    the requested boxes is bit identical, including the alpha channel.
    """

    base = _open_png(base_png, 'base_png')
    items = _parse_overlays(overlays, base.width, base.height)
    catalog = _load_font(font_bytes)
    missing = sorted(
        {
            character
            for item in items
            for character in item['text']
            if character != '\n' and ord(character) not in catalog.covered
        }
    )
    if missing:
        raise _error('IMAGE_GLYPH_MISSING', f'the font has no glyph for {_codepoints(missing)}')
    output = base.convert('RGBA')
    for item in items:
        _draw_overlay(output, item, catalog)
    buffer = BytesIO()
    output.save(buffer, format='PNG')
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# optional local Tesseract OCR
# ---------------------------------------------------------------------------

def _ocr_path(value: object, name: str) -> Path:
    """Absolute path for a caller supplied executable or tessdata directory."""

    if isinstance(value, (bytes, bytearray)):
        raise _error('IMAGE_OCR_PATH_INVALID', f'{name} must be a string path, not bytes')
    try:
        text = os.fspath(value)
    except TypeError as error:
        raise _error(
            'IMAGE_OCR_PATH_INVALID',
            f'{name} must be a path-like value, got {type(value).__name__}',
        ) from error
    if not isinstance(text, str):
        raise _error('IMAGE_OCR_PATH_INVALID', f'{name} must be a string path, not bytes')
    if text == '':
        raise _error('IMAGE_OCR_PATH_INVALID', f'{name} must not be empty')
    if '\x00' in text:
        raise _error('IMAGE_OCR_PATH_INVALID', f'{name} must not contain NUL')
    return Path(os.path.abspath(text))


def _ocr_language(language: object, tessdata: Path) -> str:
    """Validate ``[a-z_]+`` segments joined by ``+`` and their traineddata."""

    if not isinstance(language, str) or language == '':
        raise _error('IMAGE_OCR_LANGUAGE_INVALID', 'language must be a non empty string')
    for part in language.split('+'):
        if _LANGUAGE_PATTERN.match(part) is None:
            raise _error(
                'IMAGE_OCR_LANGUAGE_INVALID',
                f'language segment {part!r} must match [a-z_]+',
            )
        if not (tessdata / f'{part}.traineddata').is_file():
            raise _error('IMAGE_OCR_LANGUAGE_NOT_FOUND', f'missing {part}.traineddata in tessdata')
    return language


def _ocr_timeout(timeout: object) -> int:
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        raise _error(
            'IMAGE_OCR_TIMEOUT_INVALID', f'timeout must be an integer, got {type(timeout).__name__}'
        )
    if timeout < MIN_OCR_TIMEOUT or timeout > MAX_OCR_TIMEOUT:
        raise _error(
            'IMAGE_OCR_TIMEOUT_INVALID',
            f'timeout must be between {MIN_OCR_TIMEOUT} and {MAX_OCR_TIMEOUT} seconds',
        )
    return timeout


def _ocr_environment(executable: Path) -> dict:
    """Minimal Windows environment: system directories, temps and exe PATH.

    Nothing else is inherited, so API keys, proxy credentials and unrelated
    variables never reach the child process.
    """

    environment = {}
    for name in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP'):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    environment['PATH'] = str(executable.parent)
    return environment


def _ocr_payload(png: bytes, image: Image.Image) -> bytes:
    """PNG bytes for stdin; transparent input is flattened on white here only."""

    if image.mode in ('RGBA', 'LA', 'PA', 'RGBa') or 'transparency' in image.info:
        rgba = image.convert('RGBA')
        background = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        buffer = BytesIO()
        Image.alpha_composite(background, rgba).convert('RGB').save(buffer, format='PNG')
        return buffer.getvalue()
    return png


def _tsv_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise _error('IMAGE_OCR_TSV_INVALID', f'TSV field is not an integer: {value!r}') from error


def _tsv_confidence(value: str) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError) as error:
        raise _error('IMAGE_OCR_TSV_INVALID', f'TSV confidence is not a number: {value!r}') from error
    if not math.isfinite(confidence):
        raise _error('IMAGE_OCR_TSV_INVALID', 'TSV confidence is not a finite number')
    return confidence


def _wide(character: str) -> bool:
    """True for East Asian wide/fullwidth characters (kana, CJK, fullwidth)."""

    return unicodedata.east_asian_width(character) in ('W', 'F')


def _join_ocr_words(words: list) -> str:
    """Join TSV words of one line; CJK neighbours stay unseparated."""

    parts: list = []
    previous = ''
    for word in words:
        if previous and not _wide(previous[-1]) and not _wide(word[0]):
            parts.append(' ')
        parts.append(word)
        previous = word
    return ''.join(parts).strip()


def _parse_ocr_tsv(payload: bytes, width: int, height: int) -> list:
    """Parse Tesseract TSV output into ``box``/``text``/``confidence`` lines.

    Words are grouped by ``block_num``/``par_num``/``line_num``.  Empty words
    and negative confidence are ignored; a word box outside the image is a
    hard error rather than a silently dropped region.  Each returned region
    carries the union box, the joined line text and the mean word confidence.
    """

    if not isinstance(payload, (bytes, bytearray)):
        raise _error('IMAGE_OCR_TSV_INVALID', 'TSV output is not bytes')
    try:
        text = bytes(payload).decode('utf-8')
    except UnicodeDecodeError as error:
        raise _error('IMAGE_OCR_TSV_INVALID', 'TSV output is not valid UTF-8') from error
    rows = [row for row in text.replace('\r\n', '\n').replace('\r', '\n').split('\n') if row != '']
    if not rows:
        raise _error('IMAGE_OCR_TSV_INVALID', 'TSV output is empty')
    header = rows[0].lstrip('\ufeff').split('\t')
    columns = {}
    for name in _TSV_FIELDS:
        try:
            columns[name] = header.index(name)
        except ValueError:
            raise _error('IMAGE_OCR_TSV_INVALID', f'TSV header has no {name!r} column') from None
    groups: dict = {}
    for row in rows[1:]:
        fields = row.split('\t')
        if len(fields) < len(header):
            raise _error('IMAGE_OCR_TSV_INVALID', 'TSV row has fewer fields than the header')
        if _tsv_int(fields[columns['level']]) != _WORD_LEVEL:
            continue
        confidence = _tsv_confidence(fields[columns['conf']])
        word = '\t'.join(fields[columns['text']:]).strip()
        if confidence < 0 or word == '':  # empty word and negative confidence are ignored
            continue
        left = _tsv_int(fields[columns['left']])
        top = _tsv_int(fields[columns['top']])
        box_width = _tsv_int(fields[columns['width']])
        box_height = _tsv_int(fields[columns['height']])
        if (
            left < 0
            or top < 0
            or box_width < 0
            or box_height < 0
            or left + box_width > width
            or top + box_height > height
        ):
            raise _error('IMAGE_OCR_BOX_OUT_OF_BOUNDS', 'a TSV word box is outside the image')
        key = (
            _tsv_int(fields[columns['block_num']]),
            _tsv_int(fields[columns['par_num']]),
            _tsv_int(fields[columns['line_num']]),
        )
        group = groups.get(key)
        if group is None:
            group = {
                'left': left,
                'top': top,
                'right': left + box_width,
                'bottom': top + box_height,
                'words': [],
                'confidences': [],
            }
            groups[key] = group
        else:
            group['left'] = min(group['left'], left)
            group['top'] = min(group['top'], top)
            group['right'] = max(group['right'], left + box_width)
            group['bottom'] = max(group['bottom'], top + box_height)
        group['words'].append(word)
        group['confidences'].append(confidence)
    regions = []
    for group in groups.values():
        confidences = group['confidences']
        regions.append(
            {
                'box': [
                    group['left'],
                    group['top'],
                    group['right'] - group['left'],
                    group['bottom'] - group['top'],
                ],
                'text': _join_ocr_words(group['words']),
                'confidence': sum(confidences) / len(confidences),
            }
        )
    return regions


def ocr_png(
    png: bytes,
    executable,
    tessdata,
    language: str = 'jpn+eng',
    timeout: int = 45,
) -> dict:
    """Run a local Tesseract over ``png`` and return grouped text regions.

    The image is written to the child's stdin, so no Unicode input file name is
    involved.  The process runs with a minimal environment, ``shell=False``,
    ``cwd`` set to the executable directory and an absolute ``--tessdata-dir``.
    Non zero exit, timeout, oversized output and malformed TSV are all
    rejected.  The result is ``{'engine', 'language', 'regions'}``; regions are
    never turned into translation units here.
    """

    image = _open_png(png, 'png')
    executable_path = _ocr_path(executable, 'executable')
    if not executable_path.is_file():
        raise _error('IMAGE_OCR_EXECUTABLE_NOT_FOUND', f'executable is not a file: {executable_path}')
    tessdata_path = _ocr_path(tessdata, 'tessdata')
    if not tessdata_path.is_dir():
        raise _error('IMAGE_OCR_TESSDATA_NOT_FOUND', f'tessdata is not a directory: {tessdata_path}')
    selected = _ocr_language(language, tessdata_path)
    limit = _ocr_timeout(timeout)
    payload = _ocr_payload(png, image)
    argv = [
        str(executable_path),
        'stdin',
        'stdout',
        '--tessdata-dir',
        str(tessdata_path),
        '-l',
        selected,
        '--psm',
        '11',
        'tsv',
    ]
    try:
        completed = run_owned_process(
            argv,
            input=payload,
            cwd=str(executable_path.parent),
            env=_ocr_environment(executable_path),
            timeout=limit,
            stdout_limit=OCR_OUTPUT_LIMIT,
            stderr_limit=OCR_OUTPUT_LIMIT,
        )
    except OutputLimitExceeded as error:
        raise _error('IMAGE_OCR_OUTPUT_TOO_LARGE','tesseract output exceeded its bound') from error
    except subprocess.TimeoutExpired as error:
        raise _error(
            'IMAGE_OCR_TIMEOUT', f'tesseract did not finish within {limit} seconds'
        ) from error
    except OSError as error:
        # The message only names our own value; no environment content is copied.
        raise _error(
            'IMAGE_OCR_LAUNCH_FAILED', f'tesseract could not be started: {type(error).__name__}'
        ) from error
    stdout = completed.stdout or b''
    stderr = completed.stderr or b''
    if len(stdout) > OCR_OUTPUT_LIMIT or len(stderr) > OCR_OUTPUT_LIMIT:
        raise _error(
            'IMAGE_OCR_OUTPUT_TOO_LARGE', f'tesseract produced more than {OCR_OUTPUT_LIMIT} bytes'
        )
    if completed.returncode != 0:
        # stderr is deliberately not summarised: it can embed arbitrary paths.
        raise _error('IMAGE_OCR_FAILED', f'tesseract exited with status {completed.returncode}')
    return {
        'engine': 'tesseract',
        'language': selected,
        'regions': _parse_ocr_tsv(stdout, image.width, image.height),
    }
