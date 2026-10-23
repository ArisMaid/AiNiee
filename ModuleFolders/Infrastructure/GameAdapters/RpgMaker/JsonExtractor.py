"""Native MV/MZ JSON text extraction (contract v1).

Only explicitly whitelisted database fields, recognized event commands and
verified profile selectors produce writable units.  Resource names, editor
names, notes, numeric/logic values and unknown JSON are never recursed into.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from pathlib import Path

from ModuleFolders.Domain.GameProject.AdapterProtocol import ExtractionResult
from ModuleFolders.Domain.GameProject.Models import (
    Issue,
    Occurrence,
    TranslationUnit,
    hash_text,
)
from ModuleFolders.Service.GameProject.PathGuard import safe_join

from .Detector import detect_game
from .EventRules import iter_event_texts, summarize_unsupported
from .ProfileLoader import load_profile, select_values, validate_profile

__all__ = ['extract_game', 'extract_document']

_TABLE_FIELDS = {
    'Actors': ('name', 'nickname', 'profile'),
    'Classes': ('name',),
    'Items': ('name', 'description'),
    'Weapons': ('name', 'description'),
    'Armors': ('name', 'description'),
    'Skills': ('name', 'description', 'message1', 'message2'),
    'Enemies': ('name',),
    'States': ('name', 'message1', 'message2', 'message3', 'message4'),
}
_SYSTEM_TEXT_FIELDS = ('gameTitle', 'currencyUnit')
_SYSTEM_LABEL_LISTS = ('skillTypes', 'weaponTypes', 'armorTypes', 'equipTypes', 'elements')
_MAP_PATTERN = re.compile(r'\AMap\d+\Z')
_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, 'ainiee/rpgmaker-native/v1')
_MAX_SUMMARY_ISSUES = 25


def extract_game(source, profile=None, progress=None, document_cache=None) -> ExtractionResult:
    """Extract all approved standard-field and profile-verified text units."""

    info = detect_game(source)
    root = Path(info['root'])
    data_dir = info['data_dir']
    settings = _resolve_profile(profile)
    if settings and settings.get('engine') != info['engine']:
        raise ValueError('PROFILE_ENGINE_MISMATCH')
    rules = settings.get('json_rules') or []
    pending = [rule for rule in rules if rule['evidence_status'] == 'pending']

    issues = []
    profile_exclusions=[]
    files = []
    units = []
    code_counts: dict[str, int] = {}
    summaries: dict[str, int] = {}
    data_json_count = 0
    map_count = 0

    for rule in pending:
        issues.append(Issue(
            code='pending_profile_rule',
            severity='warning',
            message=f'pending json rule {rule["id"]} is a candidate only',
            path=rule['file'],
            details={
                'rule_id': rule['id'],
                'file': rule['file'],
                'selector': rule['selector'],
            },
        ))

    directory = safe_join(root, data_dir, must_exist=True)
    entries = sorted(
        (
            entry for entry in directory.iterdir()
            if entry.is_file() and entry.suffix.lower() == '.json'
        ),
        key=lambda entry: entry.name,
    )

    for entry_index,entry in enumerate(entries):
        if progress:progress(entry_index,len(entries),entry.name)
        relative_path = f'{data_dir}/{entry.name}'
        try:
            payload = safe_join(root, relative_path, must_exist=True).read_bytes()
        except OSError as error:
            if document_cache is not None:
                raise ValueError('EXTRACTION_SOURCE_READ_FAILED: '+relative_path) from error
            issues.append(Issue(
                code='file_read_error',
                severity='error',
                message=str(error),
                path=relative_path,
            ))
            data_json_count += 1
            if _MAP_PATTERN.match(entry.stem):
                map_count += 1
            continue

        def compute(_path=relative_path, _payload=payload):
            return extract_document(_path, _payload, settings)

        if document_cache is None:
            result = compute()
        else:
            result = document_cache(relative_path, payload, settings, compute)
            if not isinstance(result, ExtractionResult):
                raise ValueError('EXTRACTION_CACHE_INVALID_RESULT')

        files.extend(result.files)
        units.extend(result.units)
        issues.extend(result.issues)
        file_stats = result.stats
        data_json_count += file_stats.get('data_json_count', 0)
        map_count += file_stats.get('map_count', 0)
        for key, count in (file_stats.get('code_counts') or {}).items():
            code_counts[key] = code_counts.get(key, 0) + count
        for key, count in (file_stats.get('unsupported_commands') or {}).items():
            summaries[key] = summaries.get(key, 0) + count
        profile_exclusions.extend(file_stats.get('profile_exclusions') or [])

    if progress:progress(len(entries),len(entries),'complete')

    for key in sorted(summaries)[:_MAX_SUMMARY_ISSUES]:
        issues.append(Issue(
            code='unsupported_command_candidate',
            severity='warning',
            message=f'{key}: {summaries[key]} occurrence(s)',
            details={'command': key, 'count': summaries[key]},
        ))

    stats = {
        'data_json_count': data_json_count,
        'map_count': map_count,
        'code_counts': code_counts,
        'unsupported_commands': summaries,
        'unit_count': len(units),
        'profile_excluded_count':len(profile_exclusions),'profile_exclusions':profile_exclusions,
    }
    return ExtractionResult(
        units=tuple(units),
        issues=tuple(issues),
        files=tuple(files),
        stats=stats,
    )


def _normalize_document_path(relative_path) -> str:
    if not isinstance(relative_path, str):
        raise ValueError('EXTRACTION_INVALID_PATH: relative_path must be a string')
    if not relative_path:
        raise ValueError('EXTRACTION_INVALID_PATH: relative_path is empty')
    path = relative_path.replace('\\', '/')
    if path.startswith('/'):
        raise ValueError('EXTRACTION_INVALID_PATH: absolute or UNC path')
    if ':' in path:
        raise ValueError('EXTRACTION_INVALID_PATH: drive or colon')
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise ValueError('EXTRACTION_INVALID_PATH: ASCII control character')
    parts = path.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise ValueError('EXTRACTION_INVALID_PATH: empty, dot or dotdot component')
    if any(part.endswith('.') or part.endswith(' ') for part in parts):
        raise ValueError('EXTRACTION_INVALID_PATH: trailing dot or space')
    if not path.lower().endswith('.json'):
        raise ValueError('EXTRACTION_INVALID_PATH: not a .json file')
    return path


def extract_document(relative_path, payload, settings=None) -> ExtractionResult:
    """Parse one RPG Maker JSON document without touching the filesystem."""

    relative_path = _normalize_document_path(relative_path)
    if not isinstance(payload, bytes):
        raise ValueError('EXTRACTION_INVALID_PAYLOAD: payload must be bytes')
    if settings is None:
        settings = {}
    elif not isinstance(settings, Mapping):
        raise ValueError('EXTRACTION_INVALID_SETTINGS: settings must be a mapping')

    name = relative_path.rsplit('/', 1)[-1]
    stem = name[:-5]
    metadata = {
        'relative_path': relative_path,
        'sha256': hashlib.sha256(payload).hexdigest(),
        'size': len(payload),
        'encoding': '',
    }
    issues = []
    stats = {
        'data_json_count': 1,
        'map_count': 1 if _MAP_PATTERN.match(stem) else 0,
        'code_counts': {},
        'unsupported_commands': {},
        'unit_count': 0,
        'profile_excluded_count': 0,
        'profile_exclusions': [],
    }
    try:
        document, encoding = _parse_json(payload)
    except (UnicodeDecodeError, ValueError) as error:
        issues.append(Issue(
            code='json_parse_error',
            severity='error',
            message=f'{name}: {error}',
            path=relative_path,
        ))
        return ExtractionResult(
            units=(), issues=tuple(issues), files=(metadata,), stats=stats,
        )
    metadata['encoding'] = encoding

    specs: list[dict] = []
    seen: set[str] = set()

    def add(spec, _specs=specs, _seen=seen):
        address=spec.get('address',spec['pointer'])
        if address in _seen:
            raise ValueError('EXTRACTION_WRITE_CONFLICT: '+relative_path+spec['pointer'])
        _seen.add(address)
        _specs.append(spec)

    code_counts: dict[str, int] = {}
    summaries: dict[str, int] = {}
    exclusions = []
    command_fields = {
        'positions': settings.get('command_text_fields') or {},
        'plugins': settings.get('plugin_commands') or [],
        'literal_issues': issues,
    }
    file_commands=dict(command_fields,event_literals=[rule for rule in settings.get('event_literals',[])
        if rule['file']==relative_path])
    if stem in _TABLE_FIELDS:
        _table_specs(stem, document, add)
    elif stem == 'System':
        _system_specs(document, add)
    elif stem == 'CommonEvents':
        _common_event_specs(document, add, file_commands, summaries, code_counts)
    elif stem == 'Troops':
        _troop_specs(document, add, file_commands, summaries, code_counts)
    elif _MAP_PATTERN.match(stem):
        _map_specs(stem, document, add, file_commands, summaries, code_counts)
    for rule in settings.get('json_rules') or []:
        if rule['evidence_status'] == 'verified' and _file_matches(rule['file'], relative_path):
            _profile_specs(rule, document, add, exclusions)

    from .EventWriteGuard import check_event_target
    from .JsonPatcher import _parse_pointer
    for spec in specs:
        check_event_target(document, relative_path, _parse_pointer(spec['pointer']),
                           spec.get('locator_extra', {}).get('value_codec'))
    units = _units_from_specs(relative_path, specs)
    stats['code_counts'] = code_counts
    stats['unsupported_commands'] = summaries
    stats['unit_count'] = len(units)
    stats['profile_excluded_count'] = len(exclusions)
    stats['profile_exclusions'] = exclusions
    return ExtractionResult(
        units=tuple(units),
        issues=tuple(issues),
        files=(metadata,),
        stats=stats,
    )


# ---------------------------------------------------------------------------
# standard database fields
# ---------------------------------------------------------------------------

def _table_specs(stem: str, document, add) -> None:
    if not isinstance(document, list):
        return
    for index, entry in enumerate(document):
        if not isinstance(entry, Mapping):
            continue
        entry_id = entry.get('id', index)
        scene_id = f'{stem}:{entry_id}'
        for field in _TABLE_FIELDS[stem]:
            text = _text(entry.get(field))
            if text is None:
                continue
            add(_spec(
                f'/{index}/{field}', text, field, f'{stem}.{field}', scene_id,
                {'table': stem, 'entry_id': entry_id, 'field': field},
            ))


def _system_specs(document, add) -> None:
    if not isinstance(document, Mapping):
        return
    for field in _SYSTEM_TEXT_FIELDS:
        text = _text(document.get(field))
        if text is not None:
            add(_spec(
                f'/{field}', text, f'system.{field}', f'system.{field}', 'system',
                {'table': 'System', 'field': field},
            ))
    terms = document.get('terms')
    if isinstance(terms, Mapping):
        def visit(value, pointer):
            if isinstance(value, str) and value.strip():
                add(_spec(pointer, value, 'system.term', 'system.term', 'system',
                          {'table': 'System', 'field': pointer}))
            elif isinstance(value, Mapping):
                for key, child in value.items():
                    visit(child, pointer + '/' + _escape_token(str(key)))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, pointer + '/' + str(index))
        visit(terms, '/terms')
    for field in _SYSTEM_LABEL_LISTS:
        values = document.get(field)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            text = _text(value)
            if text is None:
                continue
            add(_spec(
                f'/{field}/{index}', text, f'system.{field}', f'system.{field}',
                'system', {'table': 'System', 'field': field, 'index': index},
            ))


# ---------------------------------------------------------------------------
# recognized event lists
# ---------------------------------------------------------------------------

def _map_specs(stem: str, document, add, command_fields, summaries, code_counts) -> None:
    if not isinstance(document, Mapping):
        return
    text = _text(document.get('displayName'))
    if text is not None:
        add(_spec(
            '/displayName', text, 'map_display_name', 'map_display_name', stem,
            {'table': 'Map', 'map_id': stem},
        ))
    events = document.get('events')
    if not isinstance(events, list):
        return
    for event_index, event in enumerate(events):
        if not isinstance(event, Mapping):
            continue
        pages = event.get('pages')
        if not isinstance(pages, list):
            continue
        event_id = event.get('id', event_index)
        for page_index, page in enumerate(pages):
            if not isinstance(page, Mapping):
                continue
            _event_specs(
                page.get('list'),
                f'/events/{event_index}/pages/{page_index}/list',
                f'{stem}:event:{event_id}:page:{page_index}',
                add, command_fields, summaries, code_counts,
            )


def _common_event_specs(document, add, command_fields, summaries, code_counts) -> None:
    if not isinstance(document, list):
        return
    for index, entry in enumerate(document):
        if not isinstance(entry, Mapping):
            continue
        event_id = entry.get('id', index)
        _event_specs(
            entry.get('list'), f'/{index}/list', f'common_event:{event_id}',
            add, command_fields, summaries, code_counts,
        )


def _troop_specs(document, add, command_fields, summaries, code_counts) -> None:
    if not isinstance(document, list):
        return
    for index, entry in enumerate(document):
        if not isinstance(entry, Mapping):
            continue
        pages = entry.get('pages')
        if not isinstance(pages, list):
            continue
        troop_id = entry.get('id', index)
        for page_index, page in enumerate(pages):
            if not isinstance(page, Mapping):
                continue
            _event_specs(
                page.get('list'), f'/{index}/pages/{page_index}/list',
                f'troop:{troop_id}:page:{page_index}',
                add, command_fields, summaries, code_counts,
            )


def _event_specs(commands, pointer_prefix, scene_id, add, command_fields, summaries, code_counts) -> None:
    if not isinstance(commands, list):
        return
    for command in commands:
        if isinstance(command, Mapping) and type(command.get('code')) is int:
            key = str(command['code'])
            code_counts[key] = code_counts.get(key, 0) + 1
    for key, count in summarize_unsupported(commands).items():
        summaries[key] = summaries.get(key, 0) + count
    for item in iter_event_texts(commands, pointer_prefix,
            command_text_fields=command_fields.get('positions'),
            plugin_command_rules=command_fields.get('plugins', [])):
        context = {'code': item.code, 'command_index': item.command_index}
        if item.speaker:
            context['speaker'] = item.speaker
        if item.code == 102:
            questions = _choice_question_pointers(commands, item.command_index, pointer_prefix)
            if questions:
                context['choice_question_pointers'] = questions
        add(_spec(
            item.pointer, item.text, item.role, item.kind, scene_id, context,
            item.group, item.code,
        ))
    for rule in command_fields.get('event_literals',[]):
        if scene_id not in rule['scene_ids']:continue
        if rule['evidence_status']!='verified':
            command_fields['literal_issues'].append(Issue('pending_event_literal_rule','warning',
                'Event display literal needs consumer evidence',path=rule['file'],details={'rule_id':rule['id'],'scene_id':scene_id}))
            continue
        from ModuleFolders.Domain.GameProject.EventLiteralCodec import decode_literal,CODEC_ID
        for index,command in enumerate(commands):
            if not isinstance(command,Mapping) or type(command.get('code')) is not int or command['code']!=122:continue
            values=command.get('parameters')
            if (not isinstance(values,list) or len(values)!=5 or any(type(value) is not int for value in values[:4])
                    or values[:4]!=[rule['variable_id'],rule['variable_id'],0,4]):continue
            pointer=f'{pointer_prefix}/{index}/parameters/4'
            try:text=decode_literal(values[4])
            except ValueError:
                command_fields['literal_issues'].append(Issue('EVENT_LITERAL_UNSUPPORTED','warning',
                    'Approved display variable uses a non-literal expression; retained unchanged',path=rule['file'],
                    details={'rule_id':rule['id'],'pointer':pointer,'scene_id':scene_id}))
                continue
            if not text.strip():continue
            context={'code':122,'command_index':index,'rule_id':rule['id'],'variable_id':rule['variable_id']}
            if rule.get('preserve_js_zero'):context['value_constraints']={'preserve_js_zero':True}
            spec=_spec(pointer,text,rule['role'],rule.get('kind','menu'),scene_id,context,code=122)
            spec['locator_extra']={'value_codec':CODEC_ID,'raw_expression':values[4]}
            spec['raw_expected']=values[4]
            add(spec)


def _choice_question_pointers(commands, choice_index, prefix):
    """Prove command101 -> consecutive401 -> immediate102 source ownership.

    The engine's command101 consumes the consecutive401 block, then handles an
    immediately following102 in the same message. A nearby earlier message, an
    orphan401, scroll text or another branch does not establish this relation.
    Require matching valid indents as an additional malformed-input guard.
    Only pointer provenance is added; writable fields and stable IDs are unchanged.
    """
    level = commands[choice_index].get('indent')
    if type(level) is not int or level < 0:
        return []
    pointers = []
    index = choice_index - 1
    while index >= 0:
        command = commands[index]
        if (not isinstance(command, Mapping) or type(command.get('code')) is not int
                or command['code'] != 401):
            break
        if type(command.get('indent')) is not int or command['indent'] != level:
            return []
        parameters = command.get('parameters')
        if isinstance(parameters, list) and parameters and _text(parameters[0]) is not None:
            pointers.append(f'{prefix}/{index}/parameters/0')
        index -= 1
    if not pointers or index < 0:
        return []
    start = commands[index]
    if (not isinstance(start, Mapping) or type(start.get('code')) is not int
            or start['code'] != 101 or type(start.get('indent')) is not int
            or start['indent'] != level):
        return []
    return list(reversed(pointers))


def _profile_specs(rule, document, add, exclusions) -> None:
    for pointer, value in select_values(document, rule['selector']):
        text = _text(value)
        if text is None:
            continue
        reason='exact_value' if text in rule.get('exclude_values',[]) else (
            'contains_marker' if any(value in text for value in rule.get('exclude_contains',[])) else '')
        if reason:
            exclusions.append({'rule_id':rule['id'],'path':rule['file'],'pointer':pointer,'reason':reason})
            continue
        context={'table':'profile','rule_id':rule['id'],'selector':rule['selector']}
        raw=None
        note_extra=None
        span_extra=None
        if rule.get('note_tag'):
            from ModuleFolders.Domain.GameProject.NoteTagText import value_match,validate_locator
            match=value_match(text,rule['note_tag'],last_wins=rule.get('note_last_wins',False))
            if match is None or not match[3].strip():continue
            note_extra={'pointer':pointer,'note_tag':rule['note_tag'],'raw_note':text}
            if rule.get('shared_note'):note_extra['note_group']=True
            if rule.get('note_last_wins'):note_extra['note_last_wins']=True
            validate_locator(rule['file'],note_extra)
            raw=text;text=match[3]
            if text in rule.get('exclude_values',[]):
                exclusions.append({'rule_id':rule['id'],'path':rule['file'],'pointer':pointer,'reason':'exact_note_value'})
                continue
            index=int(pointer.split('/')[1]);entry_id=document[index].get('id',index)
            context.update(note_tag=rule['note_tag'],table=Path(rule['file']).stem,entry_id=entry_id,field='note')
        if rule.get('value_codec'):
            raw=text
            if rule['value_codec']=='event-js-span-v1':
                from ModuleFolders.Domain.GameProject.EventScriptSpan import validate_source
                from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import _call
                span=validate_source(raw,rule['event_script_span'])
                rows=_call({'operation':'extract_spans','source':raw,'spans':[span]})
                text=rows[0]['value']
                if hash_text(text)!=span['expected_sha256']:raise ValueError('EVENT_SCRIPT_TEXT_MISMATCH')
                span_extra={'value_codec':rule['value_codec'],'raw_expression':raw,'event_script_span':span,'span_text':text}
                context['script_fragment_id']=span['id']
            else:
                from ModuleFolders.Domain.GameProject.EventLiteralCodec import decode_line_literal
                text=decode_line_literal(raw)
            if not text.strip():continue
        constraints={key:rule[key] for key in ('exclude_values','exclude_contains','preserve_js_zero') if rule.get(key)}
        if note_extra:
            constraints['exclude_contains']=list(dict.fromkeys([*constraints.get('exclude_contains',[]),'<','>']))
            constraints['preserve_newlines']=True
        if constraints:context['value_constraints']=constraints
        spec=_spec(
            pointer, text, rule['role'], rule.get('kind', rule['role']),
            f'{context["table"]}:{context["entry_id"]}' if note_extra else rule.get('scene_id',f'profile:{rule["id"]}'),
            context,
        )
        if raw is not None:
            spec['raw_expected']=raw
            spec['locator_extra']=span_extra or ({key:value for key,value in note_extra.items() if key!='pointer'} if note_extra else
                {'value_codec':rule['value_codec'],'raw_expression':raw})
        if rule.get('shared_note'):spec['address']=pointer+'#note:'+rule['note_tag']
        if span_extra:spec['address']=pointer+'#event-span:'+span_extra['event_script_span']['id']
        add(spec)


# ---------------------------------------------------------------------------
# unit assembly
# ---------------------------------------------------------------------------

def _units_from_specs(relative_path: str, specs) -> list:
    groups: dict[str, list] = {}
    order: list[str] = []
    for spec in specs:
        key = spec['group'] or 'occurrence:'+spec.get('address',spec['pointer'])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(spec)

    units = []
    for key in order:
        items = groups[key]
        primary = items[0]
        occurrences = tuple(
            Occurrence(
                occurrence_id=_stable_id(
                    'occurrence', relative_path, item.get('address',item['pointer']), item['role']
                ),
                relative_path=relative_path,
                locator={'pointer': item['pointer'],**item.get('locator_extra',{})},
                expected_value_hash=hash_text(item.get('raw_expected',item['text'])),
                role=item['role'],
                ordinal=ordinal,
            )
            for ordinal, item in enumerate(items)
        )
        units.append(TranslationUnit(
            unit_id=_stable_id('unit', relative_path, primary.get('address',primary['pointer']), primary['role']),
            kind=primary['kind'],
            source_text=primary['text'],
            scene_id=primary['scene_id'],
            context=dict(primary['context']),
            occurrences=occurrences,
        ))
    return units


def _spec(pointer, text, role, kind, scene_id, context, group='', code=None) -> dict:
    return {
        'pointer': pointer,
        'text': text,
        'role': role,
        'kind': kind,
        'scene_id': scene_id,
        'context': context,
        'group': group,
        'code': code,
    }


def _stable_id(*parts) -> str:
    return str(uuid.uuid5(_NAMESPACE, '|'.join(str(part) for part in parts)))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _resolve_profile(profile) -> dict:
    if profile is None:
        return {}
    if isinstance(profile, Mapping):
        return validate_profile(profile)
    return load_profile(profile)


def _parse_json(payload: bytes):
    if payload.startswith(b'\xef\xbb\xbf'):
        return json.loads(payload.decode('utf-8-sig')), 'utf-8-sig'
    return json.loads(payload.decode('utf-8')), 'utf-8'


def _file_matches(rule_file: str, relative_path: str) -> bool:
    wanted = rule_file.replace('\\', '/').strip('/').lower()
    candidate = relative_path.replace('\\', '/').lower()
    if candidate == wanted or candidate.endswith('/' + wanted):
        return True
    return '/' not in wanted and candidate.rsplit('/', 1)[-1] == wanted


def _escape_token(token: str) -> str:
    return token.replace('~', '~0').replace('/', '~1')


def _text(value):
    if isinstance(value, str) and value.strip() != '':
        return value
    return None
