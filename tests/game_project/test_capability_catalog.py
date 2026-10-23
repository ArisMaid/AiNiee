import json
import pytest
from ModuleFolders.Infrastructure.GameAdapters.Capabilities import capability_matrix,route_support


def test_catalog_is_a_truthful_isolated_json_snapshot():
    matrix=capability_matrix()
    assert set(matrix)=={'rpgmaker-native','js-literal','image-region','stev','rpgmtl','sextractor'}
    for cid,entry in matrix.items():
        assert entry['adapter_id']==cid
        assert entry['version'] and entry['validated_fixture_sets']
        assert set(entry['supports'].values())<={'verified','unsupported','unverified'}
        if entry['component_type']=='document_backend':
            assert entry['validated_game_profiles']==[]
            assert entry['write_ownership']=='whole_file_exclusive'
            assert entry['supports']['arbitrary_custom_fields']=='unverified'
    assert matrix['rpgmtl']['supports']['common_events']=='verified'
    assert matrix['rpgmtl']['supports']['explicit_js_literals']=='verified'
    assert matrix['rpgmtl']['formats']==['json','js']
    assert matrix['rpgmaker-native']['supports']['general_js_literals']=='unsupported'
    matrix['rpgmtl']['supports'].clear()
    assert capability_matrix()['rpgmtl']['supports']['common_events']=='verified'
    json.dumps(capability_matrix(),allow_nan=False)


def test_route_capability_never_grants_external_write_without_proof():
    assert route_support('native','data/Items.json')['status']=='supported'
    for backend in ('stev','rpgmtl','sextractor'):
        result=route_support(backend,'DATA\\Items.JSON')
        assert result['status']=='candidate_required'
        assert result['ownership']=='whole_file_exclusive'
        for path in ('../data/Items.json','C:/data/Items.json','data//Items.json'):
            assert route_support(backend,path)['status']=='unsupported'
        assert route_support(backend,'data/words.js')['status']==('candidate_required' if backend=='rpgmtl' else 'unsupported')
    assert route_support('rpgmtl','data/CommonEvents.json')['status']=='candidate_required'
    assert route_support('rpgmtl','Items.json')['status']=='unsupported'
    assert route_support('stev','Items.json')['status']=='unsupported'
    assert route_support('stev','other/Items.json')['status']=='unsupported'
    for backend in ('other','js-literal','image-region'):
        with pytest.raises(ValueError,match='BACKEND_UNKNOWN'):route_support(backend,'data/Items.json')
