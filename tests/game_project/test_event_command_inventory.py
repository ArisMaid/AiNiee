import copy
import hashlib
import json

import pytest

from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.EventCommandInventory import inventory_document


def cmd(code, *parameters):
    return {'code': code, 'indent': 0, 'parameters': list(parameters)}


def test_known_containers_exact_locations_and_input_unchanged():
    commands = [cmd(401, '台詞'), cmd(355, 'first();'), cmd(655, 'second();'),
                cmd(356, 'Legacy 日本'), cmd(655, 'orphan();'),
                cmd(357, 'P', 'show', '表示', {'text': '表示', 'id': '日本', 'n': 1, 'x/y~': ''})]
    document = {'events': [None, {'id': 7, 'pages': [{'list': commands}]}],
                'unknown': {'code': 355, 'parameters': ['ignored']}}
    original = copy.deepcopy(document)
    checked = []
    rules = [{'plugin': 'P', 'command': 'show', 'fields': ['text', 'x/y~'], 'evidence_status': 'verified'},
             {'plugin': 'P', 'command': 'show', 'fields': ['id'], 'evidence_status': 'pending'}]
    rows = inventory_document('www/data/Map007.json', document, plugin_rules=rules, check=lambda: checked.append(1))
    assert document == original
    assert len(checked) >= len(commands)
    assert [r['code'] for r in rows] == [355, 356, 655, 357]
    first = rows[0]
    assert first['pointer'] == '/events/1/pages/0/list/1'
    assert first['scene_id'] == 'Map007:event:7:page:0'
    assert first['parameter_pointers'] == ['/events/1/pages/0/list/1/parameters', '/events/1/pages/0/list/2/parameters']
    assert first['command_count'] == 2
    assert first['raw_commands'] == commands[1:3]
    expected = hashlib.sha256(json.dumps(commands[1:3], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    assert first['source_sha256'] == expected
    assert rows[1]['plugin'] == 'Legacy'
    assert rows[-1]['approved_fields'] == ['text']
    assert rows[-1]['unreviewed_fields'] == ['id', 'n', 'x/y~']
    assert all(r['writes_enabled'] is False for r in rows)
    first['raw_commands'][0]['parameters'][0] = 'mutated output'
    assert document == original


@pytest.mark.parametrize('path,document,scene,pointer', [
    ('data/CommonEvents.json', [None, {'id': 0, 'list': [cmd(355, 'a')]}], 'common_event:0', '/1/list/0'),
    ('data/Troops.json', [None, {'pages': [{'list': [cmd(356, 'P value')]}]}], 'troop:1:page:0', '/1/pages/0/list/0'),
])
def test_other_engine_lists(path, document, scene, pointer):
    row, = inventory_document(path, document)
    assert (row['scene_id'], row['pointer'], row['path']) == (scene, pointer, path)


def test_no_language_gate_or_arbitrary_json_recursion_and_bad_shapes():
    commands = [cmd(True, 'bad'), cmd(355.0, 'bad'), None, {'code': 357},
                cmd(357, None, 1, None, ['bad']), cmd(355, 'ASCII only')]
    document = [None, {'list': commands}, {'list': 'bad'}]
    rows = inventory_document('data/CommonEvents.json', document, plugin_rules=[None, {}, {'fields': None}])
    assert [r['code'] for r in rows] == [357, 357, 355]
    assert all(r['plugin'] == '' for r in rows)
    assert inventory_document('data/Custom.json', document) == []
    assert inventory_document('data/map1.json', {'events': []}) == []
    assert inventory_document('data/Map1.json', []) == []


def test_cancellation_is_not_swallowed():
    def check():
        raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError, match='cancelled'):
        inventory_document('data/CommonEvents.json', [{'list': [cmd(401, 'normal')]}], check=check)
