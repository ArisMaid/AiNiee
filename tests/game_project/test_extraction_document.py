"""Per-file seam preserves the native output including read-only provenance.

The v23 golden delta adds only two proven choice-question pointer lists; stable
unit IDs, occurrences, source text, file hashes, order and diagnostics stay fixed.
"""
from dataclasses import asdict
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import test_adapter_acceptance as fixtures
from ModuleFolders.Domain.GameProject.AdapterProtocol import ExtractionResult
from ModuleFolders.Domain.GameProject.Models import TranslationUnit,Issue
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker import JsonExtractor


def fixture_profile():
    return {'schema_version':1,'id':'document-fixture','engine':'rpgmaker-mz','json_rules':[
        {'id':'message','file':'data/RandomTalk.json','selector':'/*/message',
         'value_type':'string','role':'dialogue','evidence_status':'verified'},
        {'id':'pending','file':'data/RandomTalk.json','selector':'/*/voiceId',
         'value_type':'string','role':'dialogue','evidence_status':'pending'}]}


def fixture_game():
    fixture=fixtures.AdapterAcceptance();fixture.setUp()
    return fixture.root,fixture_profile()


def serialized(result):
    return json.loads(json.dumps(asdict(result),ensure_ascii=False))


def test_aggregate_matches_pre_refactor_golden_output():
    root,profile=fixture_game()
    expected=json.loads(Path(__file__).with_name('native_document_golden.json').read_text(encoding='utf-8'))
    assert serialized(JsonExtractor.extract_game(root,profile))==expected


def test_cold_and_warm_cache_keep_order_stats_and_all_diagnostics():
    root,profile=fixture_game();cold=JsonExtractor.extract_game(root,profile)
    cache={};computed=[];progress=[]
    def cached(path,payload,settings,compute):
        if path not in cache:
            cache[path]=compute();computed.append(path)
        return cache[path]
    first=JsonExtractor.extract_game(root,profile,document_cache=cached)
    assert serialized(first)==serialized(cold)
    assert len(computed)==4
    with patch.object(JsonExtractor,'_parse_json',side_effect=AssertionError('cached input was parsed again')):
        second=JsonExtractor.extract_game(root,profile,document_cache=cached,
            progress=lambda done,total,label:progress.append((done,total,label)))
    assert serialized(second)==serialized(cold)
    assert [done for done,_,_ in progress]==list(range(5))
    assert len([i for i in second.issues if i.code=='pending_profile_rule'])==1


def test_document_parser_is_pure_and_collects_per_file_diagnostics():
    root,profile=fixture_game();payload=(root/'data/Map001.json').read_bytes()
    with patch.object(Path,'open',side_effect=AssertionError('document parser accessed filesystem')):
        result=JsonExtractor.extract_document('data/Map001.json',payload,profile)
    assert result.stats['data_json_count']==1 and result.stats['map_count']==1
    assert result.stats['code_counts']['401']==2
    assert result.stats['unsupported_commands']['script']==1
    assert not any(i.code in {'pending_profile_rule','unsupported_command_candidate'} for i in result.issues)
    assert result.files[0]['relative_path']=='data/Map001.json'
    bad=JsonExtractor.extract_document('data/Items.json',b'not json',{})
    assert bad.files[0]['encoding']=='' and bad.units==()
    assert [i.code for i in bad.issues]==['json_parse_error']
    for path in ('../Items.json','C:/Items.json','/Items.json','data//Items.json','data/../Items.json'):
        with pytest.raises(ValueError):JsonExtractor.extract_document(path,b'[]',{})
    with pytest.raises(ValueError):JsonExtractor.extract_document('data/Items.json','[]',{})
    with pytest.raises(ValueError):JsonExtractor.extract_document('data/Items.json',b'[]','profile.yaml')


def test_cache_must_return_an_extraction_result():
    root,profile=fixture_game()
    with pytest.raises(ValueError):
        JsonExtractor.extract_game(root,profile,document_cache=lambda *args:{'units':[]})


def test_cached_read_failure_stops_at_the_named_document():
    root,profile=fixture_game();actual=Path.read_bytes
    def fail(path):
        if path.name=='Items.json':raise OSError('injected read error')
        return actual(path)
    with patch.object(Path,'read_bytes',fail):
        with pytest.raises(ValueError,match='EXTRACTION_SOURCE_READ_FAILED: data/Items.json'):
            JsonExtractor.extract_game(root,profile,document_cache=lambda path,data,settings,compute:compute())
