"""Real upstream entrypoint, independent phases and declared disk effects."""
import hashlib,json,os,shutil
from pathlib import Path
from unittest.mock import patch
import pytest
from ModuleFolders.Infrastructure.GameAdapters import CompatibilityBridge as bridge

SDK=Path(__file__).resolve().parents[2]/'work/vendor/SExtractor'
pytestmark=pytest.mark.skipif(not (SDK/'src/main_extract.py').is_file(),reason='Pinned optional SExtractor is not installed')

def digest(raw):return hashlib.sha256(raw).hexdigest()

def pipeline(tmp_path,document,changes,backend=SDK):
    raw=b'\xef\xbb\xbf'+json.dumps(document,ensure_ascii=False,indent=2).replace('\n','\r\n').encode()
    before={p:p.read_bytes() for p in (backend/'src').glob('*.py')}
    config=(backend/'src/engine.ini').read_bytes()
    result=bridge.rewrite_document('sextractor','data/System.json',raw,changes,tmp_path/'后端 空格',backend)
    proof=json.loads(Path(result['sidecar_path']).read_text(encoding='utf-8'))
    assert result['capabilities']['main_entrypoint'] is True
    assert result['capabilities']['memory_only'] is False and result['capabilities']['third_party_write_api'] is True
    p=proof['pipeline'];assert p['entrypoint']=='main_extract_json.mainExtractJson -> main_extract.mainExtract'
    assert p['config_sha256']==digest(config) and proof['source_sha256']==digest(raw)
    assert [r['operation'] for r in p['phases']]==['extract','import']
    assert len({r['pid'] for r in p['phases']}|{os.getpid()})==3
    allowed={'extract':{'src/engine.ini','document/input.json','document/ctrl/all.orig.json'},
        'import':{'src/engine.ini','document/input.json','document/ctrl/all.orig.json','document/ctrl/all.trans.json','document/new/input.json'}}
    for phase in p['phases']:
        root=Path(phase['root']);assert root.is_relative_to(tmp_path)
        assert phase['entrypoint_sha256']==digest((backend/'src/main_extract.py').read_bytes())
        assert {r['path'] for r in phase['manifest']}==allowed[phase['operation']]
        assert {r.relative_to(root).as_posix() for r in root.rglob('*') if r.is_file()}==allowed[phase['operation']]
        assert (root/'document/input.json').read_bytes()==raw and (root/'src/engine.ini').read_bytes()==config
        assert all(digest((root/r['path']).read_bytes())==r['sha256'] for r in phase['manifest'])
        assert not list((root.parent/'cwd').iterdir())
    actual=Path(p['phases'][1]['root'])/'document/new/input.json'
    assert result['output_bytes']==actual.read_bytes() and p['upstream_output_sha256']==digest(actual.read_bytes())
    assert not list((Path(result['sidecar_path']).parent/'cwd').iterdir())
    assert before=={p:p.read_bytes() for p in before}
    assert config==(backend/'src/engine.ini').read_bytes()
    return json.loads(result['output_bytes'].decode('utf-8-sig')),proof

def test_actual_main_entrypoint_preserves_duplicate_occurrences_and_multiline_arrays(tmp_path):
    document={'terms':{'commands':['同文😀','同文😀','','設定'],'messages':[['第一行\r\n第二行','未改动']]},
        'rows':[{'caption':'同文😀','resource':'内部ID'}],'flags':[True,1,1.0,None]}
    changes=[{'pointer':'/terms/commands/0','source_text':'同文😀','text':'甲菜单'},
        {'pointer':'/terms/commands/1','source_text':'同文😀','text':'乙菜单'},
        {'pointer':'/terms/messages/0/0','source_text':'第一行\r\n第二行','text':'中文一行\r\n中文二行'},
        {'pointer':'/rows/0/caption','source_text':'同文😀','text':'第三位置'}]
    expected=json.loads(json.dumps(document));expected['terms']['commands'][:2]=['甲菜单','乙菜单']
    expected['terms']['messages'][0][0]='中文一行\r\n中文二行';expected['rows'][0]['caption']='第三位置'
    actual,proof=pipeline(tmp_path,document,changes)
    assert actual==expected and type(actual['flags'][1]) is int and type(actual['flags'][2]) is float
    assert {r['pointer'] for r in proof['locators']}=={r['pointer'] for r in changes}

def test_no_changes_still_executes_real_extraction_and_import(tmp_path):
    document=[None,{'name':'保持原文','description':'未改动','note':'内部ID','flags':[True,1,1.0]}]
    actual,proof=pipeline(tmp_path,document,[])
    assert actual==document and proof['locators']==[]

def test_empty_translation_and_unrequested_same_text_keep_separate_slots(tmp_path):
    document={'terms':{'commands':['同文','同文','同文']}}
    actual,_=pipeline(tmp_path,document,[{'pointer':'/terms/commands/1','source_text':'同文','text':''}])
    assert actual=={'terms':{'commands':['同文','','同文']}}

def copy_sdk(tmp_path):
    target=tmp_path/'isolated-sdk';(target/'src').mkdir(parents=True)
    names=('main_extract.py','main_extract_json.py','main_extract_part.py','var_extract.py','common.py',
        'helper_text.py','helper_read.py','helper_write.py','extract_TXT.py','extract_RPGMV.py','engine.ini')
    for name in names:shutil.copy2(SDK/'src'/name,target/'src'/name)
    return target

def test_actual_entrypoint_unlisted_disk_write_is_refused_without_fallback(tmp_path):
    sdk=copy_sdk(tmp_path)
    with (sdk/'src/main_extract.py').open('a',encoding='utf-8') as handle:
        handle.write('\n_real_main = mainExtract\ndef mainExtract(args, initDone=None):\n'
            '    result = _real_main(args, initDone)\n'
            '    with open(os.path.join(var.workpath,"unexpected.bin"),"wb") as output: output.write(b"bad")\n'
            '    return result\n')
    with pytest.raises(ValueError,match='BACKEND_SIDE_EFFECT: open'):
        pipeline(tmp_path,{'name':'原文'},[{'pointer':'/name','source_text':'原文','text':'译文'}],sdk)
    assert not list(tmp_path.rglob('unexpected.bin'))

def test_candidate_cancel_between_phases_does_not_publish_or_start_import(tmp_path):
    from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
    from ModuleFolders.Service.GameProject.BackendCandidateService import generate_candidate
    from ModuleFolders.Service.GameProject.JobControl import request_action,JobCancelled
    source=tmp_path/'source';(source/'data').mkdir(parents=True);(source/'js').mkdir()
    (source/'index.html').write_text('<script src="js/rmmz_core.js"></script>',encoding='utf-8')
    (source/'js/rmmz_core.js').write_text('// rmmz_core.js v1.7.0',encoding='utf-8')
    (source/'data/System.json').write_text(json.dumps({'gameTitle':'テスト','advanced':{'gameId':1}}),encoding='utf-8')
    (source/'data/Items.json').write_text(json.dumps([None,{'id':1,'name':'回復薬','description':'説明','note':''}]),encoding='utf-8')
    completed=[];ids=[];original=bridge._run_worker
    with GameProjectService.create(source,tmp_path/'project') as service:
        service.extract();unit=next(u for u in service.store.units() if u.source_text=='回復薬')
        service.import_translations({unit.unit_id:'恢复药'});accepted=service.store.translation(unit.unit_id)
        def run(raw,run_dir,backend):
            response=original(raw,run_dir,backend);operation=json.loads(raw).get('operation')
            completed.append(operation)
            if operation=='sextractor_main_extract':request_action(service.store,ids[0],'cancel')
            return response
        with patch.object(bridge,'_run_worker',side_effect=run):
            with pytest.raises(JobCancelled):
                generate_candidate(service.store,'sextractor',SDK,'data/Items.json',on_job=lambda job:ids.append(job['job_id']))
        assert completed==['sextractor_main_extract']
        assert not list((service.store.root/'work/candidates').glob('*/data/Items.json'))
        assert service.store.translation(unit.unit_id)==accepted
