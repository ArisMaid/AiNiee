"""Profile loading, validation and RFC6901 selector evaluation (contract v1)."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping

__all__ = ['load_profile', 'select_values', 'validate_profile']

_ENGINES = ('rpgmaker', 'rpgmaker-mv', 'rpgmaker-mz')
_STATUSES = ('verified', 'pending')
_DRIVE_PATTERN = re.compile(r'\A[A-Za-z]:')
_SOURCE_KEYS = ('source', 'game_root', 'source_root')


def load_profile(path) -> dict:
    """Load and validate a JSON or safe YAML game profile."""

    try:
        text = _read_text(path)
    except OSError as error:
        raise ValueError(f'cannot read profile: {error}') from error
    if '!!' in text:
        raise ValueError('profile contains an executable YAML tag')
    stripped = text.lstrip()
    suffix = os.path.splitext(os.fspath(path))[1].lower()
    if suffix == '.json' or stripped.startswith('{') or stripped.startswith('['):
        try:
            data = json.loads(text)
        except ValueError as error:
            raise ValueError(f'invalid JSON profile: {error}') from error
    else:
        data = _load_yaml(text)
    if data is None:
        data = {}
    return validate_profile(data)


def validate_profile(data) -> dict:
    """Return a normalized copy of ``data`` or raise :class:`ValueError`."""

    if not isinstance(data, Mapping):
        raise ValueError('profile must be a mapping')
    profile = dict(data)
    if type(profile.get('schema_version')) is not int or profile.get('schema_version') not in (1,2,3):
        raise ValueError('profile schema_version must be 1, 2 or 3')
    version=profile['schema_version']
    if version==3:
        from ModuleFolders.Domain.GameProject.Capabilities import SUPPORTED_FEATURES
        required=profile.get('required_features')
        if (not isinstance(required,list) or len(required)>32 or any(
                not isinstance(value,str) or value not in SUPPORTED_FEATURES for value in required)
                or len(set(required))!=len(required)):
            raise ValueError('profile required_features must declare unique supported capabilities')
        profile['required_features']=sorted(required)
    elif 'required_features' in profile or 'event_literals' in profile:
        raise ValueError('event literals and profile capabilities require profile schema_version 3')
    identifier = profile.get('id')
    if not isinstance(identifier, str) or identifier.strip() == '':
        raise ValueError('profile id must be a non-empty string')
    engine = profile.get('engine')
    if not isinstance(engine, str) or engine not in _ENGINES:
        raise ValueError(f'profile engine must be one of {_ENGINES}')
    for key in _SOURCE_KEYS:
        value = profile.get(key)
        if value is None or value == '':
            continue
        if not isinstance(value, str):
            raise ValueError(f'profile {key} must be a relative path string')
        _validate_relative(value, f'profile {key}')

    rules = profile.get('json_rules', [])
    if not isinstance(rules, (list, tuple)):
        raise ValueError('profile json_rules must be a list')
    if profile['schema_version']==1 and ('token_literals' in profile or 'font_aliases' in profile or
            any(isinstance(rule,Mapping) and any(key in rule for key in
                ('exclude_values','exclude_contains','preserve_js_zero')) for rule in rules)):
        raise ValueError('literal tokens, font aliases and display value constraints require profile schema_version 2')
    profile['json_rules'] = [
        _validate_rule(rule, index) for index, rule in enumerate(rules)
    ]
    if any(rule.get('value_codec') for rule in profile['json_rules']) and version!=3:
        raise ValueError('event script line rules require profile schema_version 3')
    if any(rule.get('note_tag') for rule in profile['json_rules']) and version!=3:
        raise ValueError('note values require profile schema_version 3')
    if 'token_literals' in profile:
        from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy
        profile['token_literals']=list(TokenPolicy(literal_tokens=profile['token_literals']).literal_tokens)
    if 'font_aliases' in profile:
        from ModuleFolders.Domain.GameProject.FontPolicy import normalize_aliases
        profile['font_aliases']=normalize_aliases(profile['font_aliases'])
        if profile['font_aliases'] and engine!='rpgmaker-mz':raise ValueError('FONT_ALIASES_REQUIRE_MZ')
    seen = set()
    for rule in profile['json_rules']:
        if rule['id'] in seen:
            raise ValueError(f'duplicate json rule id: {rule["id"]}')
        seen.add(rule['id'])

    fields = profile.get('command_text_fields')
    if fields is not None and not isinstance(fields, Mapping):
        raise ValueError('profile command_text_fields must be a mapping')
    from .EventWriteGuard import normalize_command_fields
    normalize_command_fields(fields)
    plugins = profile.get('plugin_commands', [])
    if not isinstance(plugins, list):
        raise ValueError('plugin_commands must be a list')
    for rule in plugins:
        if not isinstance(rule, Mapping) or rule.get('evidence_status') not in _STATUSES:
            raise ValueError('invalid plugin command rule')
        if any(not isinstance(rule.get(k), str) or not rule[k] for k in ('plugin','command')):
            raise ValueError('plugin and command must be strings')
        if not isinstance(rule.get('fields'), list) or not all(isinstance(x,str) and x for x in rule['fields']):
            raise ValueError('plugin fields must be string list')
    event_rules=profile.get('event_literals',[])
    if not isinstance(event_rules,list):raise ValueError('event_literals must be a list')
    ids=set()
    for rule in event_rules:
        if (not isinstance(rule,Mapping) or set(rule)-{'id','file','scene_ids','variable_id','role','kind',
                'codec','preserve_js_zero','evidence_status'}):raise ValueError('invalid event literal rule')
        if not isinstance(rule.get('id'),str) or not rule['id'] or rule['id'] in ids:raise ValueError('invalid/duplicate event literal id')
        ids.add(rule['id'])
        if not isinstance(rule.get('file'),str):raise ValueError('event literal file is required')
        _validate_relative(rule['file'],'event literal file')
        if '*' in rule['file'] or not rule['file'].endswith('.json'):raise ValueError('event literal needs an exact JSON file')
        scenes=rule.get('scene_ids')
        if not isinstance(scenes,list) or not scenes or any(not isinstance(v,str) or not v for v in scenes) or len(set(scenes))!=len(scenes):
            raise ValueError('event literal scene_ids must be a unique nonempty list')
        if type(rule.get('variable_id')) is not int or not 1<=rule['variable_id']<=999999:raise ValueError('invalid event literal variable_id')
        if rule.get('codec')!='event-js-json-string-v1':raise ValueError('unsupported event literal codec')
        if rule.get('evidence_status') not in _STATUSES:raise ValueError('invalid event literal evidence status')
        if not isinstance(rule.get('role'),str) or not rule['role']:raise ValueError('event literal role is required')
        if 'kind' in rule and (not isinstance(rule['kind'],str) or not rule['kind']):raise ValueError('invalid event literal kind')
        if 'preserve_js_zero' in rule and type(rule['preserve_js_zero']) is not bool:raise ValueError('preserve_js_zero must be bool')
    js_rules=profile.get('js_rules',[])
    if not isinstance(js_rules,list):raise ValueError('js_rules must be a list')
    for rule in js_rules:
        if not isinstance(rule,Mapping):raise ValueError('invalid JS rule')
        if 'source_spans' in rule or 'source_sha256' in rule:
            from ModuleFolders.Domain.GameProject.EncodedJsonText import script_span,text_affixes
            if version!=3 or any(k in rule for k in ('scope_function','property_fields','static_text','literal_path','json_texts','json_scripts')):
                raise ValueError('source spans require an unmixed profile-3 rule')
            spans=rule.get('source_spans')
            if not isinstance(spans,list) or not 1<=len(spans)<=256:raise ValueError('invalid source_spans')
            ids=set();ranges=[]
            for span in spans:
                if not isinstance(span,dict):raise ValueError('invalid source span')
                script_span({**span,'source_sha256':rule.get('source_sha256')})
                if 'text_affixes' in span:text_affixes(span['text_affixes'])
                if span['id'] in ids or not isinstance(span.get('expected_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',span['expected_sha256']):
                    raise ValueError('invalid source span identity or text hash')
                ids.add(span['id']);ranges.append((span['start'],span['end']))
            ranges.sort()
            if any(a[1]>b[0] for a,b in zip(ranges,ranges[1:])):raise ValueError('overlapping source spans')
            if not isinstance(rule.get('object_path'),str) or not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]{0,127}',rule['object_path']):
                raise ValueError('source spans require an identity namespace')
            if not isinstance(rule.get('file'),str):raise ValueError('source spans require an exact JS file')
            _validate_relative(rule['file'],'source spans file')
            if '*' in rule['file'] or not rule['file'].endswith('.js'):raise ValueError('source spans require an exact JS file')
        if any(k in rule for k in ('literal_path','json_texts','json_scripts')):
            from ModuleFolders.Domain.GameProject.EncodedJsonText import literal_path,normalize_steps,script_span
            if version!=3 or any(k in rule for k in ('scope_function','property_fields','static_text')):
                raise ValueError('encoded JS parameters require an exact profile-3 literal path')
            literal_path(rule.get('literal_path'))
            if 'json_texts' in rule:
                if not isinstance(rule['json_texts'],list) or not 1<=len(rule['json_texts'])<=256:
                    raise ValueError('invalid json_texts')
                for steps in rule['json_texts']:normalize_steps(steps)
            if 'json_scripts' in rule:
                entries=rule['json_scripts']
                if not isinstance(entries,list) or not 1<=len(entries)<=256:raise ValueError('invalid json_scripts')
                for entry in entries:
                    if not isinstance(entry,dict):raise ValueError('invalid json_script')
                    normalize_steps(entry.get('json_steps'))
                    spans=entry.get('spans')
                    if not isinstance(spans,list) or not 1<=len(spans)<=256:raise ValueError('invalid json_script spans')
                    for span in spans:
                        if not isinstance(span,dict):raise ValueError('invalid json_script span')
                        script_span({**span,'source_sha256':entry.get('source_sha256')})
                        if not isinstance(span.get('expected_sha256'),str) or not re.fullmatch('[a-f0-9]{64}',span['expected_sha256']):
                            raise ValueError('invalid json_script text hash')
        if 'static_text' in rule and (version!=3 or rule['static_text'] is not True or not rule.get('scope_function')):
            raise ValueError('static_text requires profile-3 and an explicit function scope')
        if 'preserve_newlines' in rule and (version!=3 or type(rule['preserve_newlines']) is not bool):
            raise ValueError('JS preserve_newlines requires a profile-3 bool')
        if 'scope_function' in rule or 'property_fields' in rule:
            if version!=3:raise ValueError('scoped JS rules require profile schema_version 3')
            if 'scope_function' in rule and (not isinstance(rule['scope_function'],str) or
                    len(rule['scope_function'])>128 or not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*',rule['scope_function'])):
                raise ValueError('invalid JS scope_function')
            if 'scope_function' in rule and (not isinstance(rule.get('object_path'),str) or
                    len(rule['object_path'])>128 or not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*',rule['object_path'])):
                raise ValueError('scoped JS object_path must name one binding')
            values=rule.get('property_fields')
            if 'property_fields' in rule and (not isinstance(values,list) or not values or len(values)>32 or
                    any(not isinstance(value,str) or len(value)>128 or not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*',value) for value in values) or
                    len(set(values))!=len(values)):raise ValueError('invalid JS property_fields')
    if version==3:
        inferred=set()
        if profile.get('token_literals'):inferred.add('literal_tokens_v1')
        if profile.get('font_aliases'):inferred.add('font_aliases_v1')
        if any(rule.get('exclude_values') or rule.get('exclude_contains') or rule.get('preserve_js_zero') for rule in profile['json_rules']):
            inferred.add('display_value_constraints_v1')
        if event_rules:inferred.add('event_js_string_v1')
        if any(rule.get('value_codec')=='event-js-line-string-v1' for rule in profile['json_rules']):inferred.add('event_js_line_v1')
        if any(rule.get('value_codec')=='event-js-span-v1' for rule in profile['json_rules']):inferred.add('event_js_spans_v1')
        if any(rule.get('note_tag') for rule in profile['json_rules']):
            inferred.update({'note_tag_text_v1','display_line_count_v1','display_value_constraints_v1'})
        if any(rule.get('shared_note') for rule in profile['json_rules']):inferred.add('note_tag_groups_v1')
        if any(rule.get('note_last_wins') for rule in profile['json_rules']):inferred.add('note_last_value_v1')
        if any(rule.get('preserve_js_zero') for rule in event_rules):inferred.add('display_value_constraints_v1')
        if any('scope_function' in rule or 'property_fields' in rule for rule in js_rules):inferred.add('js_scoped_object_v1')
        if any(rule.get('static_text') for rule in js_rules):inferred.add('js_display_fragments_v1')
        if any('literal_path' in rule for rule in js_rules):inferred.add('js_nested_json_v1')
        if any('source_spans' in rule for rule in js_rules):inferred.add('js_source_spans_v1')
        if any('text_affixes' in span for rule in js_rules for span in rule.get('source_spans',[])):
            inferred.add('js_fixed_affixes_v1')
        if any(rule.get('preserve_newlines') for rule in js_rules):
            inferred.update({'display_line_count_v1','display_value_constraints_v1'})
        if inferred-set(profile['required_features']):raise ValueError('profile required_features omits active capabilities')
    return profile


def select_values(document, selector) -> list:
    """Iterate ``selector`` matches as ``(pointer, value)`` tuples.

    Only ``/`` separated RFC6901 tokens are supported; ``*`` matches every
    current-level member of a list (by index) or a mapping (by key).  Pointers
    returned use canonical RFC6901 escaping.
    """

    return list(_walk(document, _selector_tokens(selector), ''))


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _read_text(path) -> str:
    try:
        with open(os.fspath(path), 'rb') as handle:
            payload = handle.read()
    except TypeError as error:
        raise ValueError(f'profile path must be a string: {path!r}') from error
    try:
        return payload.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise ValueError('profile must be UTF-8 encoded') from error


def _load_yaml(text: str):
    try:
        import yaml
    except ImportError as error:  # pragma: no cover - optional dependency
        raise ValueError('YAML profiles require PyYAML') from error
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(f'invalid YAML profile: {error}') from error


def _validate_rule(rule, index: int) -> dict:
    if not isinstance(rule, Mapping):
        raise ValueError(f'json_rules[{index}] must be a mapping')
    identifier = rule.get('id')
    if not isinstance(identifier, str) or identifier.strip() == '':
        raise ValueError(f'json_rules[{index}] id must be a non-empty string')
    if rule.get('value_type', 'string') != 'string':
        raise ValueError(f'rule {identifier} value_type must be "string"')
    role = rule.get('role')
    if not isinstance(role, str) or role.strip() == '':
        raise ValueError(f'rule {identifier} role must be a non-empty string')
    status = rule.get('evidence_status', 'pending')
    if status not in _STATUSES:
        raise ValueError(f'rule {identifier} evidence_status must be one of {_STATUSES}')
    file = rule.get('file')
    if not isinstance(file, str):
        raise ValueError(f'rule {identifier} file must be a string')
    normalized = {
        'id': identifier,
        'file': _validate_relative(file, f'rule {identifier} file'),
        'selector': _validate_selector(rule.get('selector'), identifier),
        'value_type': 'string',
        'role': role,
        'evidence_status': status,
    }
    for key in ('kind', 'description'):
        if isinstance(rule.get(key), str):
            normalized[key] = rule[key]
    if 'note_tag' in rule:
        from ModuleFolders.Domain.GameProject.NoteTagText import tag_name
        if normalized['selector']!='/*/note' or 'value_codec' in rule:
            raise ValueError('note values require /*/note and no event codec')
        normalized['note_tag']=tag_name(rule['note_tag'])
    if 'shared_note' in rule:
        if 'note_tag' not in normalized or type(rule['shared_note']) is not bool:
            raise ValueError('shared_note requires a note tag and bool')
        if rule['shared_note']:normalized['shared_note']=True
    if 'note_last_wins' in rule:
        if 'note_tag' not in normalized or type(rule['note_last_wins']) is not bool:
            raise ValueError('note_last_wins requires a note tag and bool')
        if rule['note_last_wins']:normalized['note_last_wins']=True
    if 'value_codec' in rule:
        if rule['value_codec'] not in ('event-js-line-string-v1','event-js-span-v1'):raise ValueError('unsupported profile value_codec')
        if '*' in normalized['selector']:raise ValueError('event script lines require an exact pointer')
        if not isinstance(rule.get('scene_id'),str) or not rule['scene_id']:raise ValueError('event script line scene_id required')
        normalized['value_codec']=rule['value_codec'];normalized['scene_id']=rule['scene_id']
    if rule.get('value_codec')=='event-js-span-v1':
        from ModuleFolders.Domain.GameProject.EventScriptSpan import span_spec
        if not normalized['file'].endswith('.json') or '*' in normalized['file']:raise ValueError('event script spans require an exact JSON file')
        normalized['event_script_span']=span_spec(rule.get('event_script_span'))
    elif 'event_script_span' in rule:raise ValueError('event_script_span requires its explicit codec')
    for key in ('exclude_values','exclude_contains'):
        values=rule.get(key,[])
        if (not isinstance(values,(list,tuple)) or len(values)>64 or
            any(not isinstance(v,str) or not v or len(v)>256 or '\x00' in v for v in values) or
            len(set(values))!=len(values)):
            raise ValueError(f'rule {identifier} {key} must be a unique bounded string list')
        if values:normalized[key]=list(values)
    if 'preserve_js_zero' in rule:
        if type(rule['preserve_js_zero']) is not bool:raise ValueError('preserve_js_zero must be bool')
        if rule['preserve_js_zero']:normalized['preserve_js_zero']=True
    return normalized


def _validate_relative(value: str, name: str) -> str:
    text = value.replace('\\', '/')
    if text.startswith('/') or _DRIVE_PATTERN.match(text):
        raise ValueError(f'{name} must be relative: {value!r}')
    for segment in text.split('/'):
        if segment in ('', '.', '..') or ':' in segment:
            raise ValueError(f'{name} must not contain traversal or empty segments: {value!r}')
    return text


def _validate_selector(value, rule_id: str) -> str:
    tokens = _selector_tokens(value, rule_id)
    for token in tokens:
        if '*' in token and token != '*':
            raise ValueError(f'rule {rule_id} selector only supports whole "*" segments')
    return value


def _selector_tokens(value, rule_id: str = '') -> tuple:
    prefix = f'rule {rule_id} ' if rule_id else ''
    if not isinstance(value, str) or value == '' or not value.startswith('/'):
        raise ValueError(f'{prefix}selector must be an RFC6901 pointer starting with "/"')
    tokens = []
    for raw in value.split('/')[1:]:
        if re.search(r'~(?![01])', raw):
            raise ValueError('invalid RFC6901 selector escape')
        if raw == '':
            raise ValueError(f'{prefix}selector must not contain empty segments')
        token = raw.replace('~1', '/').replace('~0', '~')
        if token in ('.', '..'):
            raise ValueError(f'{prefix}selector must not contain traversal segments')
        if '\x00' in token:
            raise ValueError(f'{prefix}selector must not contain NUL')
        tokens.append(token)
    if not tokens:
        raise ValueError(f'{prefix}selector must address at least one field')
    return tuple(tokens)


def _walk(node, tokens: tuple, pointer: str):
    if not tokens:
        yield pointer, node
        return
    token, rest = tokens[0], tokens[1:]
    if token == '*':
        if isinstance(node, Mapping):
            for key, child in node.items():
                yield from _walk(child, rest, f'{pointer}/{_escape(str(key))}')
        elif isinstance(node, list):
            for index, child in enumerate(node):
                yield from _walk(child, rest, f'{pointer}/{index}')
        return
    if isinstance(node, Mapping):
        if token in node:
            yield from _walk(node[token], rest, f'{pointer}/{_escape(token)}')
    elif isinstance(node, list):
        if token.isdigit():
            index = int(token)
            if 0 <= index < len(node):
                yield from _walk(node[index], rest, f'{pointer}/{index}')


def _escape(token: str) -> str:
    return token.replace('~', '~0').replace('/', '~1')
