import json

import pytest

from ModuleFolders.Domain.GameProject.Models import hash_text
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.EventRules import iter_event_texts
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonExtractor import extract_document
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import compile_json_changes, patch_json
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.ProfileLoader import validate_profile


def profile(**extra):
    return dict(schema_version=1, id='guard', engine='rpgmaker-mz', **extra)


@pytest.mark.parametrize('code', [108, 408, 657, 111, 122, 205, 355, 655, 356, 357])
def test_raw_event_override_is_refused_by_profile_and_direct_helper(code):
    with pytest.raises(ValueError, match='UNSAFE_EVENT_TEXT_OVERRIDE'):
        validate_profile(profile(command_text_fields={str(code): [0]}))
    with pytest.raises(ValueError, match='UNSAFE_EVENT_TEXT_OVERRIDE'):
        iter_event_texts([{'code': code, 'parameters': ['日本']}], '/0/list', command_text_fields={code: 0})


@pytest.mark.parametrize('code', [111, 122, 205, 355, 655, 356])
@pytest.mark.parametrize('name,document,pointer', [
    ('CommonEvents.json', lambda command: [None, {'list': [command]}], '/1/list/0/parameters/0'),
    ('Troops.json', lambda command: [None, {'pages': [{'list': [command]}]}], '/1/pages/0/list/0/parameters/0'),
    ('Map001.json', lambda command: {'events': [None, {'pages': [{'list': [command]}]}]}, '/events/1/pages/0/list/0/parameters/0'),
])
def test_old_untyped_units_and_generic_selectors_cannot_write_executable_parameters(code, name, document, pointer):
    path = 'data/' + name
    source = json.dumps(document({'code': code, 'parameters': ['日本']}), ensure_ascii=False).encode()
    occurrence = {'relative_path': path, 'expected_value_hash': hash_text('日本'), 'locator': {'pointer': pointer}}
    for writer in (patch_json, compile_json_changes):
        with pytest.raises(ValueError, match='UNSAFE_EVENT_STRING_TARGET'):
            writer(source, [(occurrence, '中文')])
    rule = {'id': 'unsafe', 'file': path, 'selector': pointer, 'role': 'dialogue', 'evidence_status': 'verified'}
    with pytest.raises(ValueError, match='UNSAFE_EVENT_STRING_TARGET'):
        extract_document(path, source, profile(json_rules=[rule]))


@pytest.mark.parametrize('slot', [0, 1, 2])
def test_plugin_invocation_identity_is_not_plain_display_text(slot):
    path = 'data/CommonEvents.json'
    source = json.dumps([{'list': [{'code': 357, 'parameters': ['日本', '日本', '日本', {'text': '日本'}]}]}], ensure_ascii=False).encode()
    occurrence = {'relative_path': path, 'expected_value_hash': hash_text('日本'),
                  'locator': {'pointer': f'/0/list/0/parameters/{slot}'}}
    with pytest.raises(ValueError, match='UNSAFE_EVENT_STRING_TARGET'):
        patch_json(source, [(occurrence, '中文')])
    occurrence['locator']['pointer'] = '/0/list/0/parameters/3/text'
    assert json.loads(patch_json(source, [(occurrence, '中文')]))[0]['list'][0]['parameters'][3]['text'] == '中文'


@pytest.mark.parametrize('code,values', [(355, ['"日本"']), (122, [2, 3, 0, 4, '"日本"']),
                                      (122, [2, 2, 1, 4, '"日本"']), (122, [True, True, 0, 4, '"日本"'])])
def test_literal_codec_cannot_be_attached_to_script_or_different_assignment(code, values):
    slot = 0 if code == 355 else 4
    raw = values[slot]
    source = json.dumps([{'list': [{'code': code, 'parameters': values}]}], ensure_ascii=False).encode()
    occurrence = {'relative_path': 'data/CommonEvents.json', 'expected_value_hash': hash_text(raw),
                  'locator': {'pointer': f'/0/list/0/parameters/{slot}', 'value_codec': 'event-js-json-string-v1', 'raw_expression': raw}}
    for writer in (patch_json, compile_json_changes):
        with pytest.raises(ValueError, match='EVENT_LITERAL_TARGET_INVALID'):
            writer(source, [(occurrence, '中文')])


def test_custom_json_lookalike_and_explicit_safe_override_remain_supported():
    source = json.dumps([{'list': [{'code': 355, 'parameters': ['日本']}]}], ensure_ascii=False).encode()
    occurrence = {'relative_path': 'data/Custom.json', 'expected_value_hash': hash_text('日本'),
                  'locator': {'pointer': '/0/list/0/parameters/0'}}
    assert json.loads(patch_json(source, [(occurrence, '中文')]))[0]['list'][0]['parameters'][0] == '中文'
    items = iter_event_texts([{'code': 401, 'parameters': ['日本']}], '/0/list', command_text_fields={'401': [0]})
    assert items[0].text == '日本'


def test_build_of_historical_untyped_script_unit_is_refused_without_publication():
    import test_adapter_acceptance as fixtures
    from ModuleFolders.Domain.GameProject.Models import TranslationUnit, Occurrence
    from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
    fixture = fixtures.AdapterAcceptance()
    fixture.setUp()
    project = fixture.root.parent / (fixture.root.name + '-historical-script')
    output = fixture.root.parent / (fixture.root.name + '-unsafe-output')
    raw = 'if (x === "保持") y();'
    with GameProjectService.create(fixture.root, project) as service:
        service.extract()
        unit = TranslationUnit(unit_id='historical-script', kind='command_text', source_text=raw,
            source_hash=hash_text(raw), scene_id='Map001:event:1:page:0', context={'code': 355},
            occurrences=(Occurrence(occurrence_id='historical-script-occ', relative_path='data/Map001.json',
                locator={'pointer': '/events/1/pages/0/list/7/parameters/0'}, expected_value_hash=hash_text(raw),
                role='command_text', ordinal=0),))
        service.store.replace_units([*service.store.units(), unit])
        assert service.import_translations({unit.unit_id: '中文'})[0].status == 'accepted'
        with pytest.raises(ValueError, match='UNSAFE_EVENT_STRING_TARGET'):
            service.build(output, test=True)
        assert not list(output.glob('*/build-manifest.json'))
        original = json.loads((fixture.root / 'data/Map001.json').read_text(encoding='utf-8'))
        assert original['events'][1]['pages'][0]['list'][7]['parameters'][0] == raw
