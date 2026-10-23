import codecs
import copy
import json
from pathlib import Path

import pytest
import test_adapter_acceptance as fixtures
from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import rewrite_document
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import semantic_differences
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BackendRoutes import configure_route
from ModuleFolders.Service.GameProject.BuildService import BuildService, file_hash

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / 'work/vendor/RPGMTL'


def common_document():
    def c(code, *values):
        return {'code': code, 'indent': 0, 'parameters': list(values)}
    def event(event_id, name):
        return {'id': event_id, 'name': name, 'trigger': 0, 'switchId': 1, 'list': [
            c(101, 'Face', 0, 0, 2, '話者'), c(401, '同文'), c(102, ['同文', '別選択'], 0, 0, 2, 0),
            c(402, 0, '同文'), c(404), c(357, 'Display', 'show', 'editor', {'text': '表示', 'id': '資源識別子'}),
            c(355, 'keep("日本");'), c(655, 'follow();'), c(0)]}
    # Upstream read/write disagree on an empty first 355 line followed by
    # 655. This unrelated event must not be walked for a different child.
    unrelated = {'id': 20, 'name': 'Unrequested script', 'trigger': 0, 'switchId': 1,
                 'list': [c(355, ''), c(655, 'keep();'), c(0)]}
    return [None, event(7, 'First/Editor'), event(12, 'Second'), unrelated]


@pytest.mark.parametrize('relative_path', ['data/CommonEvents.json', '中文 空格/www/data/CommonEvents.json'])
@pytest.mark.parametrize('bom', [False, True])
def test_actual_common_writer_preserves_occurrences_logic_and_source(tmp_path, relative_path, bom):
    if not BACKEND.exists():
        pytest.skip('Optional pinned RPGMTL not installed')
    document = common_document()
    payload = json.dumps(document, ensure_ascii=False, indent=2).replace('\n', '\r\n').encode()
    if bom:
        payload = codecs.BOM_UTF8 + payload
    changes = [{'pointer': p, 'source_text': source, 'text': target} for p, source, target in [
        ('/1/list/1/parameters/0', '同文', '甲'), ('/2/list/1/parameters/0', '同文', '乙'),
        ('/2/list/5/parameters/3/text', '表示', '显示')]]
    upstream_before = {name: file_hash(BACKEND / name) for name in ['plugins/json.py', 'plugins/__init__.py']}
    result = rewrite_document('rpgmtl', relative_path, payload, changes, tmp_path / 'work', BACKEND)
    output = result['output_bytes']
    assert output.startswith(codecs.BOM_UTF8) == bom
    actual = json.loads(output.decode('utf-8-sig'))
    expected = copy.deepcopy(document)
    expected[1]['list'][1]['parameters'][0] = '甲'
    expected[2]['list'][1]['parameters'][0] = '乙'
    expected[2]['list'][5]['parameters'][3]['text'] = '显示'
    assert actual == expected
    assert semantic_differences(document, actual) == {row['pointer'] for row in changes}
    locators = result['sidecar']['locators']
    assert len({row['global_id'] for row in locators}) == 3
    assert locators[0]['virtual_child'].endswith('/0007 First Editor')
    assert locators[1]['virtual_child'].endswith('/0012 Second')
    assert all(file_hash(BACKEND / name) == sha for name, sha in upstream_before.items())


def test_common_route_candidate_and_actual_routed_build(tmp_path):
    if not BACKEND.exists():
        pytest.skip('Optional pinned RPGMTL not installed')
    fixture = fixtures.AdapterAcceptance()
    fixture.setUp()
    fixture.write('CommonEvents', common_document())
    original = (fixture.root / 'data/CommonEvents.json').read_bytes()
    profile = {'schema_version': 1, 'id': 'common-event-route', 'engine': 'rpgmaker-mz',
        'plugin_commands': [{'plugin': 'Display', 'command': 'show', 'fields': ['text'], 'evidence_status': 'verified'}]}
    with GameProjectService.create(fixture.root, tmp_path / 'project') as service:
        service.extract(profile)
        changes = {unit.unit_id: ('甲' if unit.scene_id == 'common_event:7' else '乙')
            for unit in service.store.units() if unit.source_text == '同文' and unit.kind == 'dialogue'
            and unit.scene_id.startswith('common_event:')}
        assert len(changes) == 2
        assert all(result.status == 'accepted' for result in service.import_translations(changes))
        route = configure_route(service.store, 'data/CommonEvents.json', 'rpgmtl', BACKEND)
        assert route['backend'] == 'rpgmtl'
        built = service.build(tmp_path / 'output', test=True)
        assert next(row for row in built['files'] if row['path'] == 'data/CommonEvents.json')['writer']['id'] == 'rpgmtl'
        output = Path(built['output_path']) / 'data/CommonEvents.json'
        actual = json.loads(output.read_text(encoding='utf-8-sig'))
        assert actual[1]['list'][1]['parameters'][0] == '甲' and actual[2]['list'][1]['parameters'][0] == '乙'
        assert actual[1]['list'][2:] == common_document()[1]['list'][2:]
        assert BuildService.verify(built['output_path'])['passed']
    assert (fixture.root / 'data/CommonEvents.json').read_bytes() == original


def test_requested_child_with_upstream_empty_script_asymmetry_is_rejected(tmp_path):
    if not BACKEND.exists():
        pytest.skip('Optional pinned RPGMTL not installed')
    document = common_document()
    document[1]['list'][-1:-1] = [{'code': 355, 'indent': 0, 'parameters': ['']},
                                {'code': 655, 'indent': 0, 'parameters': ['keep();']}]
    payload = json.dumps(document, ensure_ascii=False).encode()
    with pytest.raises(ValueError, match='BACKEND_UPSTREAM_FAILURE'):
        rewrite_document('rpgmtl', 'data/CommonEvents.json', payload,
            [{'pointer': '/1/list/1/parameters/0', 'source_text': '同文', 'text': '甲'}], tmp_path / 'work', BACKEND)
