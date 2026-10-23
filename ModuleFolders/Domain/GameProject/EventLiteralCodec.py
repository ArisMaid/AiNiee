"""Strict JSON-string codec for RPG Maker event display literals.

Contract: docs/rpg/EVENT_LITERAL_CODEC_CONTRACT.md. This is a small JSON-string
subset codec, not a JavaScript parser: source text is only handed to ``json``,
is never executed and is never repaired or silently replaced. Profile, event
selection, occurrence mapping and write authorization belong to callers.
"""
from __future__ import annotations

import json

__all__ = ('CODEC_ID', 'LINE_CODEC_ID', 'MAX_LITERAL_BYTES', 'decode_literal', 'encode_literal',
           'decode_line_literal', 'encode_line_literal')

CODEC_ID = 'event-js-json-string-v1'
LINE_CODEC_ID = 'event-js-line-string-v1'
MAX_LITERAL_BYTES = 65536


def _utf8_size(value: str, what: str) -> int:
    """Return the UTF-8 size of ``value``, rejecting malformed Unicode."""
    try:
        return len(value.encode('utf-8'))
    except UnicodeEncodeError as exc:
        raise ValueError(f'{what} is not well-formed Unicode') from exc


def _has_lone_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def decode_literal(expression: str) -> str:
    """Decode one complete JSON string literal to its text.

    Ordinary JSON whitespace may surround the literal. Every other construct
    (numbers, booleans, null, arrays, objects, JavaScript/backtick quotes,
    concatenation, parenthesized expressions, comments, trailing statements,
    invalid escapes or lone UTF-16 surrogates) raises ValueError. Invalid input
    is never repaired or replaced.
    """
    if not isinstance(expression, str):
        raise ValueError('Event literal expression must be a string')
    if _utf8_size(expression, 'Event literal expression') > MAX_LITERAL_BYTES:
        raise ValueError(f'Event literal expression exceeds {MAX_LITERAL_BYTES} UTF-8 bytes')
    try:
        value = json.loads(expression)
    except (ValueError, RecursionError) as exc:
        # JSONDecodeError is a ValueError; RecursionError covers hostile nesting.
        raise ValueError('Event literal is not a complete JSON string value') from exc
    if not isinstance(value, str):
        raise ValueError('Event literal must be a JSON string')
    if _has_lone_surrogate(value):
        raise ValueError('Event literal decodes to a lone UTF-16 surrogate')
    return value


def encode_literal(text: str, *, original: str | None = None) -> str:
    """Encode ``text`` as a quoted JSON string literal.

    ``original`` is validated with :func:`decode_literal` first. When it decodes
    to exactly ``text`` it is returned unchanged, preserving surrounding JSON
    whitespace and the original escape spelling; otherwise a new literal is
    generated. Output larger than ``MAX_LITERAL_BYTES`` raises ValueError and is
    never truncated.
    """
    decoded = decode_literal(original) if original is not None else None
    if not isinstance(text, str):
        raise ValueError('Event literal text must be a string')
    if original is not None and decoded == text:
        return original
    # JSON escaping never shortens the text, so this also bounds the literal;
    # the exact serialized size is re-checked below.
    if _utf8_size(text, 'Event literal text') > MAX_LITERAL_BYTES:
        raise ValueError(f'Event literal text exceeds {MAX_LITERAL_BYTES} UTF-8 bytes')
    encoded = json.dumps(text, ensure_ascii=False)
    # U+2028/U+2029 are line terminators for older JavaScript string parsers.
    encoded = encoded.replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    if _utf8_size(encoded, 'Encoded event literal') > MAX_LITERAL_BYTES:
        raise ValueError(f'Encoded event literal exceeds {MAX_LITERAL_BYTES} UTF-8 bytes')
    return encoded


def _line_literal_parts(expression: str):
    """One JSON-quoted string in an explicitly approved event script line.

    Multiple strings and multiline expressions remain unsupported. The profile
    decides whether this literal is display text; this codec only preserves the
    surrounding program bytes and confines the new text to one string value.
    """
    if not isinstance(expression,str) or '\n' in expression or '\r' in expression:
        raise ValueError('EVENT_LINE_LITERAL_UNSUPPORTED')
    start=expression.find('"')
    if start<0:raise ValueError('EVENT_LINE_LITERAL_UNSUPPORTED')
    try:value,length=json.JSONDecoder().raw_decode(expression[start:])
    except ValueError as error:raise ValueError('EVENT_LINE_LITERAL_UNSUPPORTED') from error
    end=start+length
    if not isinstance(value,str) or '"' in expression[end:]:raise ValueError('EVENT_LINE_LITERAL_UNSUPPORTED')
    literal=expression[start:end]
    return start,end,decode_literal(literal)


def decode_line_literal(expression: str) -> str:
    return _line_literal_parts(expression)[2]


def encode_line_literal(text: str,*,original: str) -> str:
    start,end,decoded=_line_literal_parts(original)
    if text==decoded:return original
    return original[:start]+encode_literal(text)+original[end:]
