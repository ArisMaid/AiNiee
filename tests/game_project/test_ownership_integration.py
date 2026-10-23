"""Real extraction and legacy unsafe datasets must share one ownership gate."""
from dataclasses import asdict,replace
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import test_adapter_acceptance as fixtures

from ModuleFolders.Infrastructure.GameAdapters.Registry import RpgMakerAdapter
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BuildService import BuildService,file_hash
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner
from ModuleFolders.Service.GameProject.BackendCandidateService import generate_candidate


@pytest.fixture
def project():
    fixture=fixtures.AdapterAcceptance();fixture.setUp()
    root=fixture.root
    (root/'js/words.js').write_bytes(b'\xef\xbb\xbf'+
        "// 😀前置\r\nconst Root={words:{save:'保存'}};\r\n".encode('utf-8'))
    with GameProjectService.create(root,root.parent/(root.name+'-ownership-project')) as service:
        profile={'schema_version':1,'id':'ownership-test','engine':'rpgmaker-mz',
            'json_rules':[],'js_rules':[{'id':'words','file':'js/words.js',
                'object_path':'Root.words','evidence_status':'verified'}]}
        service.extract(profile)
        yield service,root,profile


def alias_of(unit):
    return replace(unit,unit_id=unit.unit_id+'-alias',occurrences=tuple(
        replace(o,occurrence_id=o.occurrence_id+'-alias',adapter_id='other-producer') for o in unit.occurrences))


def inject_legacy_alias(store,unit):
    """Seed an old unsafe database directly, bypassing today's store gate."""
    alias=alias_of(unit)
    with sqlite3.connect(store.root/'project.sqlite3') as db:
        db.execute('INSERT INTO units (unit_id,seq,kind,source_text,scene_id,context_json,'
            'occurrences_json,token_policy_id,source_hash,obsolete,created_at,updated_at) '
            'SELECT ?,(SELECT MAX(seq)+1 FROM units),kind,source_text,scene_id,context_json,'
            '?,token_policy_id,source_hash,0,created_at,updated_at FROM units WHERE unit_id=?',
            (alias.unit_id,json.dumps([o.to_dict() for o in alias.occurrences]),unit.unit_id))


def test_extraction_alias_rejected_before_dataset_replacement(project):
    service,root,profile=project
    unit=next(u for u in service.store.units() if u.source_text=='保存')
    assert service.import_translations({unit.unit_id:'存档'})[0].status=='accepted'
    before_meta=service.store.metadata()
    before_units=[asdict(u) for u in service.store.units()]
    before_tr=service.store.translation(unit.unit_id)
    before_sources={r['relative_path']:file_hash(root/r['relative_path']) for r in service.store.files()}
    profile=dict(profile,js_rules=profile['js_rules']+[{
        'id':'root-alias','file':'js/words.js','object_path':'Root','evidence_status':'verified'}])
    with pytest.raises(ValueError,match='EXTRACTION_WRITE_CONFLICT'):
        service.extract(profile)
    assert service.store.metadata()==before_meta
    assert [asdict(u) for u in service.store.units()]==before_units
    assert service.store.translation(unit.unit_id)==before_tr
    assert service.store.jobs()[-1]['run_state']=='FAILED'
    assert any(i['code']=='WRITE_OWNERSHIP_CONFLICT' for i in service.store.issues())
    for record in service.store.files():
        assert file_hash(root/record['relative_path'])==before_sources[record['relative_path']]
        if record.get('captured_path'):
            assert file_hash(service.store.root/record['captured_path'])==record['sha256']


def test_legacy_untranslated_alias_blocks_validation_test_build_and_sending(project):
    service,root,profile=project
    units=service.store.units()
    unit=next(u for u in units if u.source_text=='保存')
    assert service.import_translations({unit.unit_id:'存档'})[0].status=='accepted'
    items=list(build_projection(service.store).items_iter())
    inject_legacy_alias(service.store,unit)
    assert service.store.translation(unit.unit_id)['text']=='存档'
    report=service.validate()
    assert not report['passed']
    assert any(i['code']=='WRITE_OWNERSHIP_CONFLICT' for i in report['issues'])
    output=root.parent/(root.name+'-ownership-output')
    with pytest.raises(ValueError,match='WRITE_OWNERSHIP_CONFLICT'):
        service.build(output,test=True)
    assert not list(output.glob('game-zh-CN-*'))
    with pytest.raises(ValueError,match='WRITE_OWNERSHIP_CONFLICT'):
        build_projection(service.store)
    config=SimpleNamespace(request_timeout=2,project_terms_data=[])
    with pytest.raises(ValueError,match='WRITE_OWNERSHIP_CONFLICT'):
        GameBatchRunner(items,config)
    assert service.store.translation(unit.unit_id+'-alias') is None


def test_backend_candidate_rejects_legacy_alias_before_worker_call(project):
    service,root,profile=project
    units=service.store.units()
    unit=next(u for u in units if u.source_text=='回復薬')
    assert service.import_translations({unit.unit_id:'回复药'})[0].status=='accepted'
    inject_legacy_alias(service.store,unit)
    with patch('ModuleFolders.Service.GameProject.BackendCandidateService.rewrite_document') as rewrite:
        with pytest.raises(ValueError,match='WRITE_OWNERSHIP_CONFLICT'):
            generate_candidate(service.store,'stev',root,'data/Items.json')
        rewrite.assert_not_called()


def test_registry_drives_native_detection_and_extraction():
    fixture=fixtures.AdapterAcceptance();fixture.setUp()
    root=fixture.root
    with patch.object(RpgMakerAdapter,'probe',autospec=True,side_effect=RpgMakerAdapter.probe) as probe:
        with GameProjectService.create(root,root.parent/(root.name+'-registry-project')) as service:
            assert probe.call_count==1
            with patch.object(RpgMakerAdapter,'extract',autospec=True,side_effect=RpgMakerAdapter.extract) as extract:
                service.extract()
                assert extract.call_count==1
            assert service.store.metadata()['adapter_id']=='rpgmaker-native'
            assert service.store.metadata()['adapter_version']==RpgMakerAdapter.version
            assert service.validate()['passed']
            built=service.build(root.parent/(root.name+'-registry-output'),test=True)
            assert BuildService.verify(built['output_path'])['passed']


def test_store_rejects_partial_spans_before_any_dataset_write(project):
    service,root,profile=project
    units=service.store.units()
    unit=next(u for u in units if u.source_text=='保存')
    alias=alias_of(unit)
    occurrence=alias.occurrences[0]
    alias=replace(alias,occurrences=(replace(occurrence,locator=dict(occurrence.locator,
        start=occurrence.locator['start']+1)),))
    before_meta=service.store.metadata()
    before_units=[asdict(u) for u in units]
    with pytest.raises(ValueError,match='WRITE_OWNERSHIP_CONFLICT'):
        service.store.replace_units(units+[alias])
    assert service.store.metadata()==before_meta
    assert [asdict(u) for u in service.store.units()]==before_units


def test_dataset_changed_after_batch_preparation_does_not_reach_provider(project):
    service,root,profile=project
    from ModuleFolders.Service.Cache.CacheManager import CacheManager
    from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
    projection=build_projection(service.store)
    items=list(projection.items_iter())
    manager=object.__new__(CacheManager);manager.project=projection
    chunks,_,_=manager.generate_item_chunks('line',20,2,TaskType.TRANSLATION)
    # Preserve every original target, but prepare only legal real scene batches.
    assert chunks and sum(map(len,chunks))==len(items)
    assert {i.get_extra('unit_id') for chunk in chunks for i in chunk}=={
        i.get_extra('unit_id') for i in items}
    batches=[GameBatchRunner(chunk,SimpleNamespace(request_timeout=2,project_terms_data=[]))
        for chunk in chunks]
    service.store.replace_units(service.store.units()[:-1])
    requester=SimpleNamespace(sent_request=lambda *args:pytest.fail('stale dataset reached provider'))
    from ModuleFolders.Base.Base import Base
    old_status=Base.work_status
    try:
        Base.work_status=Base.STATUS.TASKING
        for batch in batches:
            with pytest.raises(ValueError,match='DATASET_REVISION_CONFLICT'):
                batch.run(requester)
    finally:Base.work_status=old_status


@pytest.mark.parametrize('routes,expected',[
    ({'data/Items.json':{'backend':['stev','rpgmtl']}},'BACKEND_ROUTE_INVALID'),
    ({'js/words.js':{'backend':'stev'}},'BACKEND_ROUTE_INVALID'),
    ({'data/Items.json':{'backend':'stev'},'DATA\\ITEMS.JSON':{'backend':'sextractor'}},'BACKEND_ROUTE_CONFLICT'),
])
def test_frozen_routes_reject_multiple_whole_file_owners_and_wrong_formats(project,routes,expected):
    service,root,profile=project
    service.store.update_metadata({'backend_routes':routes})
    report=service.validate()
    assert not report['passed']
    assert any(i['code']==expected for i in report['issues'])
    with patch('ModuleFolders.Service.GameProject.BackendRoutes.routed_write') as write:
        with pytest.raises(ValueError,match='BACKEND_ROUTE_'):
            service.build(root.parent/(root.name+'-bad-route-output'),test=True)
        write.assert_not_called()


def test_registry_rejects_false_capability_identity():
    from ModuleFolders.Infrastructure.GameAdapters.Registry import AdapterRegistry
    class BadAdapter:
        adapter_id='custom';version='1'
        def probe(self,*args):return None
        def extract(self,*args,**kwargs):return None
        def capabilities(self):return {'adapter_id':'other','version':'1'}
    with pytest.raises(ValueError,match='ADAPTER_CAPABILITY_IDENTITY_MISMATCH'):
        AdapterRegistry().register(BadAdapter())


def test_capabilities_cli_requires_no_project_and_reports_no_tool_probe(capsys):
    from Tools.rpg_pipeline import main
    assert main(['capabilities'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['availability']=='not_probed'
    assert result['external_write_requires_exact_candidate']
    assert result['capabilities']['rpgmtl']['supports']['common_events']=='verified'
