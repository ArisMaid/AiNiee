"""Explicit static template nodes in a single profiled event-script line."""
from collections.abc import Mapping
import re
from .EncodedJsonText import script_span
from .EventLiteralCodec import MAX_LITERAL_BYTES
from .Models import hash_text

CODEC_ID = 'event-js-span-v1'
FEATURE = 'event_js_spans_v1'


def span_spec(value):
    if not isinstance(value, Mapping):raise ValueError('EVENT_SCRIPT_SPAN_INVALID')
    span=dict(value);script_span(span)
    if (span['node_kind']!='template-part' or not isinstance(span.get('expected_sha256'),str)
            or not re.fullmatch('[a-f0-9]{64}',span['expected_sha256'])):
        raise ValueError('EVENT_SCRIPT_SPAN_INVALID')
    return {k:span[k] for k in ('id','start','end','node_kind','source_sha256','expected_sha256')}


def validate_source(raw, span):
    span=span_spec(span)
    if (not isinstance(raw,str) or '\n' in raw or '\r' in raw or
            len(raw.encode('utf-8'))>MAX_LITERAL_BYTES or hash_text(raw)!=span['source_sha256'] or
            span['end']>len(raw.encode('utf-8'))):
        raise ValueError('EVENT_SCRIPT_SOURCE_CHANGED')
    return span


def validate_locator(locator):
    if (not isinstance(locator,Mapping) or locator.get('value_codec')!=CODEC_ID or
            any(k in locator for k in ('note_tag','raw_note','note_group','note_last_wins'))):
        raise ValueError('EVENT_SCRIPT_LOCATOR_INVALID')
    raw=locator.get('raw_expression');span=validate_source(raw,locator.get('event_script_span'))
    text=locator.get('span_text')
    if not isinstance(text,str) or hash_text(text)!=span['expected_sha256']:
        raise ValueError('EVENT_SCRIPT_TEXT_MISMATCH')
    return raw,span,text
