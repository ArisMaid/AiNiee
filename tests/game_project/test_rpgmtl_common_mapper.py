import copy
import pytest
from ModuleFolders.Infrastructure.GameAdapters.RpgmtlCommonMapper import map_common_events


class Located(str):
    def __new__(cls, text, pointer):
        value = super().__new__(cls, text)
        value.pointer = pointer
        return value

    def __deepcopy__(self, memo):
        return Located(str(self), self.pointer)


def fixture():
    doc = [None, {'id': 7, 'name': 'A/B', 'list': [{'code': 401, 'parameters': ['同文']}]},
            {'id': 12, 'name': 'Second', 'list': [{'code': 401, 'parameters': ['同文']},
                {'code': 357, 'parameters': ['P', 'show', '', {'x/y~': '表示'}]}]}]
    a, b, c = '/1/list/0/parameters/0', '/2/list/0/parameters/0', '/2/list/1/parameters/3/x~1y~0'
    groups = [['::0007 A B'], ['Command: Text', Located('同文', a)], ['::0012 Second'],
              ['Command: Text', Located('同文', b)], ['Command: Plugin', Located('表示', c)]]
    changes = [{'pointer': p, 'source_text': old, 'text': new} for p, old, new in
               [(a, '同文', '一'), (b, '同文', '二'), (c, '表示', '显示')]]
    return doc, groups, changes


def test_virtual_children_actual_index_unique_occurrences_and_input_unchanged():
    doc, groups, changes = fixture()
    original = copy.deepcopy((doc, groups, changes))
    result = map_common_events(groups, 'www/data/CommonEvents.json', doc, changes)
    assert (doc, groups, changes) == original
    files = result['project_strings']['files']
    assert list(files) == ['www/data/CommonEvents.json/0007 A B', 'www/data/CommonEvents.json/0012 Second']
    strings = result['project_strings']['strings']
    assert len(strings) == 3 and all(row[1] is None for row in strings.values())
    assert [files[child][0][1][1] for child in files] == ['一', '二']
    assert len({entry['global_id'] for entry in result['found'].values()}) == 3
    assert result['found'][changes[0]['pointer']]['group_index'] == 1
    assert result['found'][changes[0]['pointer']]['virtual_child'].endswith('/0007 A B')
    assert all(row['ignored'] == 0 for row in result['project']['files'].values())


@pytest.mark.parametrize('change', ['wrong-child', 'bad-marker', 'duplicate-marker', 'before-marker', 'lost-pointer',
                                   'duplicate-pointer', 'wrong-old-text', 'duplicate-id', 'bool-id', 'noncanonical-index', 'traversal-token'])
def test_invalid_mapping_never_guesses(change):
    doc, groups, changes = fixture()
    if change == 'wrong-child': groups[1][1] = Located('同文', changes[1]['pointer'])
    if change == 'bad-marker': groups[0][0] = '::0999 Unknown'
    if change == 'duplicate-marker': groups.insert(2, groups[0])
    if change == 'before-marker': groups.pop(0)
    if change == 'lost-pointer': groups[1][1] = '同文'
    if change == 'duplicate-pointer': groups[1].append(groups[1][1])
    if change == 'wrong-old-text': changes[0]['source_text'] = 'another'
    if change == 'duplicate-id': doc[2]['id'] = 7
    if change == 'bool-id': doc[1]['id'] = True
    if change == 'noncanonical-index': groups[1][1] = Located('同文', '/01/list/0/parameters/0')
    if change == 'traversal-token':
        doc[2]['list'][1]['parameters'][3]['..'] = '表示'
        pointer = '/2/list/1/parameters/3/..'
        groups[-1][1] = Located('表示', pointer)
        changes[-1]['pointer'] = pointer
    with pytest.raises(ValueError, match='RPGMTL_COMMON_MAPPING_INVALID'):
        map_common_events(groups, 'data/CommonEvents.json', doc, changes)


def test_unrequested_occurrences_are_not_broadcast_and_empty_document_works():
    doc, groups, changes = fixture()
    result = map_common_events(groups, 'data/CommonEvents.json', doc, changes[:1])
    other = result['project_strings']['files']['data/CommonEvents.json/0012 Second']
    assert other[0][1][1] is None and other[0][1][4] == 0
    assert map_common_events([], 'data/CommonEvents.json', [None], [])['project_strings'] == {'strings': {}, 'files': {}}
