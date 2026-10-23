"""Explicit RPG Maker note values; all surrounding text remains opaque."""
import re
from .Models import hash_text

FEATURE = 'note_tag_text_v1'
GROUP_FEATURE = 'note_tag_groups_v1'
LAST_FEATURE = 'note_last_value_v1'
_TAGS = re.compile(r'<([^<>:]+)(:?)([^>]*)>')
_TABLES = {'Actors.json','Classes.json','Items.json','Weapons.json','Armors.json','Skills.json','Enemies.json','States.json'}


def tag_name(value):
    if not isinstance(value,str) or not value or any(c in value for c in '<>:\r\n\x00'):
        raise ValueError('NOTE_TAG_INVALID')
    return value


def value_match(raw,tag,*,last_wins=False):
    tag_name(tag)
    if not isinstance(raw,str):raise ValueError('NOTE_SOURCE_INVALID')
    matches=[m for m in _TAGS.finditer(raw) if m[1]==tag]
    if not matches:return None
    if (len(matches)!=1 and not last_wins) or matches[-1][2]!=':':raise ValueError('NOTE_TAG_AMBIGUOUS')
    return matches[-1]


def validate_locator(relative,locator):
    if (set(locator)-{'pointer','note_tag','raw_note','note_group','note_last_wins'} or
            not {'pointer','note_tag','raw_note'}<=set(locator) or
            ('note_group' in locator and locator['note_group'] is not True) or not isinstance(relative,str) or
            ('note_last_wins' in locator and locator['note_last_wins'] is not True) or
            relative.rsplit('/',1)[-1] not in _TABLES or
            not re.fullmatch(r'/(?:0|[1-9][0-9]*)/note',locator.get('pointer',''))):
        raise ValueError('NOTE_TARGET_INVALID')
    match=value_match(locator['raw_note'],locator['note_tag'],last_wins=locator.get('note_last_wins',False))
    if match is None:raise ValueError('NOTE_TAG_MISSING')
    return match[3]


def encode_value(relative,locator,expected,text):
    validate_locator(relative,locator)
    raw=locator['raw_note']
    if hash_text(raw)!=expected:raise ValueError('NOTE_SOURCE_MISMATCH')
    if not isinstance(text,str) or '<' in text or '>' in text:raise ValueError('NOTE_VALUE_DELIMITER')
    match=value_match(raw,locator['note_tag'],last_wins=locator.get('note_last_wins',False))
    return raw[:match.start(3)]+text+raw[match.end(3):]


def encode_group(relative,values):
    """Merge explicitly shared values against one immutable note, once."""
    raw=values[0][0]['raw_note'];seen=set();changes=[]
    for locator,expected,text in values:
        if locator.get('note_group') is not True or locator['raw_note']!=raw:
            raise ValueError('NOTE_GROUP_SOURCE_MISMATCH')
        encode_value(relative,locator,expected,text)
        tag=locator['note_tag']
        if tag in seen:raise ValueError('NOTE_GROUP_DUPLICATE_TAG')
        seen.add(tag);match=value_match(raw,tag,last_wins=locator.get('note_last_wins',False));changes.append((match.start(3),match.end(3),text))
    result=raw
    for start,end,text in sorted(changes,reverse=True):result=result[:start]+text+result[end:]
    return result
