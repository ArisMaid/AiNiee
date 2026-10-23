"""Actual pinned SDK + AST proof + routed build; synthetic scripts never run."""
import hashlib
import json
from pathlib import Path
import pytest
import test_adapter_acceptance as fixtures
from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import (
    extract_js_rules,compile_js_changes,audit_js_changes)
from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import rewrite_js_document
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BackendCandidateService import generate_candidate
from ModuleFolders.Service.GameProject.BackendRoutes import configure_route
from ModuleFolders.Service.GameProject.BuildService import BuildService,_checkpoint_matches

ROOT=Path(__file__).resolve().parents[2]
VENDOR=ROOT/'work/vendor/RPGMTL'
FILE='js/words.js'
RULE={'id':'approved','file':FILE,'object_path':'Kd.words','evidence_status':'verified'}
SOURCE=('// 😀 before\r\nvar Kd={};Kd.words={a:\'同文\',b:"同文",escaped:"改行\\n文字"}; '
    'var id="同文"; var template=`保持${1}`; var regex=/保持/u; '
    'throw new Error("DO_NOT_EXECUTE"); // unchanged\r\n').encode()


@pytest.mark.parametrize('bom',[b'',b'\xef\xbb\xbf'])
def test_actual_sdk_duplicate_ids_escape_transport_and_parent_proof(tmp_path,bom):
    assert VENDOR.is_dir(),'Pinned RPGMTL must be installed for acceptance'
    source=bom+SOURCE;(tmp_path/'js').mkdir();(tmp_path/FILE).write_bytes(source)
    units,issues,_=extract_js_rules(tmp_path,[RULE]);assert not issues
    texts=['甲\'"\\\r\n\t\0😀','乙','换行\n文字']
    replacements=[(unit.occurrences[0],text) for unit,text in zip(units,texts)]
    changes=compile_js_changes(source,replacements)
    watched=[VENDOR/'plugins/javascript.py',VENDOR/'plugins/__init__.py']
    hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    result=rewrite_js_document('rpgmtl',FILE,source,changes,tmp_path/'work',VENDOR)
    output=result['output_bytes'];assert output.startswith(bom) if bom else not output.startswith(b'\xef\xbb\xbf')
    assert audit_js_changes(source,output,changes)['approved_count']==3
    assert b'var id="'+ '同文'.encode()+b'"' in output
    sidecar=json.loads(Path(result['sidecar_path']).read_text(encoding='utf-8'))
    assert len({row['global_id'] for row in sidecar['locators']})==3
    assert sidecar['requested_spans']==[[row['start'],row['end']] for row in changes]
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in hashes.items())
    assert list((tmp_path/'work').glob('*/cwd/*'))==[]
    # The parent must catch a semantically harmless comment edit as well.
    with pytest.raises(ValueError):audit_js_changes(source,output.replace(b'unchanged',b'edited'),changes)


class TestRoutedJs(fixtures.unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def test_candidate_route_build_and_checkpoint_prove_approved_values(self):
        (self.root/FILE).write_bytes(b'\xef\xbb\xbf'+SOURCE)
        original=(self.root/FILE).read_bytes()
        project=self.root.parent/(self.root.name+'-js-project')
        with GameProjectService.create(self.root,project) as service:
            service.extract({'schema_version':1,'id':'synthetic-js','engine':'rpgmaker-mz','json_rules':[],
                'js_rules':[RULE]})
            js_units=[u for u in service.store.units() if any(o.relative_path==FILE for o in u.occurrences)]
            assert len(js_units)==3
            translations={unit.unit_id:['甲','乙','换行\n文字'][index] for index,unit in enumerate(js_units)}
            service.import_translations(translations)
            candidate=generate_candidate(service.store,'rpgmtl',VENDOR,FILE)
            assert candidate['passed'] and candidate['changed_occurrences']==3 and candidate['write_owner']=='js-literal'
            assert service.store.metadata().get('backend_routes',{})=={}
            configure_route(service.store,FILE,'rpgmtl',VENDOR)
            built=service.build(self.root.parent/(self.root.name+'-js-build'),test=True)
            record=next(row for row in built['files'] if row['path']==FILE)
            assert record['writer']['id']=='rpgmtl'
            assert BuildService.verify(built['output_path'])['passed']
            target=Path(built['output_path'])/FILE
            replacements=[(o,translations[u.unit_id]) for u in js_units for o in u.occurrences if o.relative_path==FILE]
            routes=service.store.metadata()['backend_routes']
            assert _checkpoint_matches(record,FILE,replacements,original,target,routes,{})
            target.write_bytes(target.read_bytes().replace(b'unchanged',b'edited'))
            assert not _checkpoint_matches(record,FILE,replacements,original,target,routes,{})
            assert (self.root/FILE).read_bytes()==original
            configure_route(service.store,FILE,'native')
            assert FILE not in service.store.metadata()['backend_routes']


@pytest.mark.parametrize('backend,path',[
    ('stev',FILE),('sextractor',FILE),('rpgmtl','js/plugins.js'),('rpgmtl','www/js/plugins.js')])
def test_unsupported_js_routes_stay_closed(backend,path):
    from ModuleFolders.Infrastructure.GameAdapters.Capabilities import route_support
    assert route_support(backend,path)['status']=='unsupported'


def test_forged_or_unavailable_span_cannot_fall_back_to_text_equality(tmp_path):
    (tmp_path/'js').mkdir();(tmp_path/FILE).write_bytes(SOURCE)
    units,_,_=extract_js_rules(tmp_path,[RULE])
    changes=compile_js_changes(SOURCE,[(units[0].occurrences[0],'甲')])
    changes[0]['start']+=1
    with pytest.raises(ValueError,match='BACKEND_LOCATOR_UNSUPPORTED'):
        rewrite_js_document('rpgmtl',FILE,SOURCE,changes,tmp_path/'work',VENDOR)
    assert not list((tmp_path/'work').glob('*/sidecar.json'))


def test_empty_request_retains_even_a_script_without_string_records(tmp_path):
    raw=b'// preserved\r\nvar count=1;\r\n'
    result=rewrite_js_document('rpgmtl',FILE,raw,[],tmp_path/'work',VENDOR)
    assert result['output_bytes']==raw and not result['capabilities']['third_party_write_api']
    assert audit_js_changes(raw,result['output_bytes'],[])['approved_count']==0
