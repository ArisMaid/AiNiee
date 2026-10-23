"""Pre-effect refusal, owned cancellation and parent evidence boundaries."""
from pathlib import Path
from unittest.mock import patch
import ctypes,hashlib,json,os,shutil,subprocess
import importlib.util,marshal,struct
from ctypes import wintypes
import pytest
from ModuleFolders.Infrastructure.GameAdapters import StevProjectBridge as bridge

SDK=Path(__file__).resolve().parents[2]/'StevExtraction'

def files():
    return {'data/Items.json':json.dumps([None,{'id':1,'name':'原文','note':''}],ensure_ascii=False).encode(),
        'data/System.json':b'{"gameTitle":"TEST"}','js/rmmz_core.js':b'// rmmz_core.js v1.7.0',
        'index.html':b'<script src="js/rmmz_core.js"></script>','img/asset.bin':b'ASSET'}

def sdk_copy(tmp_path,suffix=''):
    root=tmp_path/'sdk';root.mkdir()
    for name in ('jtpp.py','config.yaml'):shutil.copy2(SDK/name,root/name)
    if suffix:
        with (root/'jtpp.py').open('a',encoding='utf-8') as handle:handle.write(suffix)
    return root

def test_truncation_of_work_copy_source_is_denied_before_open(tmp_path):
    sdk=sdk_copy(tmp_path,'\n_real_read=Jr_Tpp.ReadGame\ndef _bad(self,GameDir):\n'
        '    fd=os.open(os.path.join(GameDir,"data","Items.json"),os.O_WRONLY|os.O_TRUNC)\n'
        '    os.write(fd,b"bad");os.close(fd)\n'
        '    return _real_read(self,GameDir)\nJr_Tpp.ReadGame=_bad\n')
    original=files()
    with pytest.raises(ValueError,match='BACKEND_SIDE_EFFECT: open'):
        bridge.rewrite_project(original,{},tmp_path/'work',sdk)
    inputs=list(tmp_path.glob('work/*/pipeline/input/data/Items.json'))
    assert len(inputs)==1 and inputs[0].read_bytes()==original['data/Items.json']
    assert not list(tmp_path.rglob('project-report.json'))

def assert_exited(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.OpenProcess(0x00100000,False,pid)
    if handle:
        try:assert kernel.WaitForSingleObject(handle,0)==0
        finally:kernel.CloseHandle(handle)
    else:assert ctypes.get_last_error()==87

def test_actual_directory_injection_running_cancel_retains_partial_without_sidecar(tmp_path):
    from ModuleFolders.Infrastructure.Platform.OwnedProcess import worker_control
    sdk=sdk_copy(tmp_path,'\n_real_inject=Jr_Tpp.InjectGame\ndef _slow(self,GameDir,path,*args,**kwargs):\n'
        '    with open(os.path.join(path,"data","Items.json"),"wb") as output: output.write(b"PARTIAL:"+str(os.getpid()).encode())\n'
        '    import time;time.sleep(30)\n'
        '    return _real_inject(self,GameDir,path,*args,**kwargs)\nJr_Tpp.InjectGame=_slow\n')
    class Cancelled(RuntimeError):pass
    def check():
        for p in tmp_path.glob('work/*/pipeline/rounds/*/data/Items.json'):
            if p.read_bytes().startswith(b'PARTIAL:'):raise Cancelled('test cancel')
    with worker_control(check):
        with pytest.raises(Cancelled):bridge.rewrite_project(files(),{},tmp_path/'work',sdk)
    partials=[p for p in tmp_path.glob('work/*/pipeline/rounds/*/data/Items.json') if p.read_bytes().startswith(b'PARTIAL:')]
    assert len(partials)==1
    assert_exited(int(partials[0].read_bytes().split(b':')[1]))
    assert not list(tmp_path.rglob('project-report.json')) and not list(tmp_path.rglob('sidecar.json'))

def test_config_fingerprint_change_blocks_full_build_before_publication(tmp_path):
    from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
    from ModuleFolders.Service.GameProject.BackendRoutes import configure_route,fingerprint
    sdk=sdk_copy(tmp_path);source=tmp_path/'game'
    for rel,raw in files().items():
        p=source/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    with GameProjectService.create(source,tmp_path/'project') as service:
        service.extract();unit=next(u for u in service.store.units() if u.source_text=='原文')
        service.import_translations({unit.unit_id:'中文'})
        route=configure_route(service.store,'data/Items.json','stev',sdk)
        assert route['proof']['changed_occurrences']==1
        assert json.loads(Path(route['proof']['candidate']).read_bytes().decode('utf-8-sig'))[1]['name']=='中文'
        before=fingerprint(sdk)
        assert 'config.yaml' in before['files']
        with (sdk/'config.yaml').open('a',encoding='utf-8') as handle:handle.write('\n# changed config\n')
        assert fingerprint(sdk)!=before
        translation=service.store.translation(unit.unit_id)
        with pytest.raises(ValueError,match='BACKEND_SOURCE_CHANGED'):
            service.build(tmp_path/'outputs',test=True)
        assert service.store.translation(unit.unit_id)==translation
    assert not list((tmp_path/'outputs').glob('game-zh-CN-*'))

def test_parent_request_persistence_failure_does_not_dispatch(tmp_path):
    with patch.object(bridge,'atomic_write',side_effect=OSError('evidence fault')):
        with patch.object(bridge,'_run_project_worker') as dispatch:
            with pytest.raises(OSError,match='evidence fault'):
                bridge.rewrite_project(files(),{},tmp_path/'work',SDK)
            dispatch.assert_not_called()
    assert not list(tmp_path.rglob('sidecar.json'))

def test_parent_does_not_trust_report_hash_as_approval(tmp_path):
    original=bridge._run_project_worker
    def tamper(request,cwd):
        response=original(request,cwd);body=json.loads(response.stdout)
        path=Path(request['case_root'])/'project-report.json'
        report=json.loads(path.read_text(encoding='utf-8'))
        report['rounds'][0]['changes'][0]['text']='UNAPPROVED'
        raw=json.dumps(report,ensure_ascii=False).encode();path.write_bytes(raw)
        body['report_sha256']=hashlib.sha256(raw).hexdigest()
        return subprocess.CompletedProcess(response.args,response.returncode,json.dumps(body).encode(),response.stderr)
    with patch.object(bridge,'_run_project_worker',side_effect=tamper):
        with pytest.raises(ValueError,match='BACKEND_UNAPPROVED_DIFF'):
            bridge.rewrite_project(files(),{'data/Items.json':[{'pointer':'/1/name','source_text':'原文','text':'中文'}]},tmp_path/'work',SDK)
    assert not list(tmp_path.rglob('sidecar.json'))

def test_pinned_source_executes_captured_python_instead_of_matching_cached_bytecode(tmp_path):
    sdk=sdk_copy(tmp_path);source=sdk/'jtpp.py';info=source.stat()
    cache=Path(importlib.util.cache_from_source(str(source)));cache.parent.mkdir()
    header=importlib.util.MAGIC_NUMBER+struct.pack('<III',0,int(info.st_mtime)&0xffffffff,info.st_size&0xffffffff)
    payload=marshal.dumps(compile('raise RuntimeError("stale SDK bytecode")',str(source),'exec'))
    cache.write_bytes(header+payload)
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    result=bridge.rewrite_project(files(),{},tmp_path/'work',sdk)
    proof=json.loads(Path(result['sidecar_path']).read_text(encoding='utf-8'))
    assert proof['jtpp_sha256']==before and proof['source_preserved'] and proof['upstream_preserved']
    from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import extract_document
    legacy=extract_document('stev','data/Items.json',files()['data/Items.json'],tmp_path/'legacy',sdk)
    assert any(row['text']=='原文' for row in legacy['records'])

def test_nested_directory_and_literal_cleanup_marker_survive_real_injection(tmp_path):
    original=files();relative='data/子目录/附加 说明.json'
    document={'caption':'附加原文','list':['☆删除☆','保留'],'flags':[True,1,1.0]}
    original[relative]=json.dumps(document,ensure_ascii=False).encode()
    result=bridge.rewrite_project(original,{relative:[{'pointer':'/caption','source_text':'附加原文','text':'附加中文'}]},tmp_path/'work',SDK)
    expected=dict(document,caption='附加中文')
    actual=json.loads(Path(result['output_paths'][relative]).read_bytes().decode('utf-8-sig'))
    assert actual==expected and type(actual['flags'][1]) is int and type(actual['flags'][2]) is float
    proof=json.loads(Path(result['sidecar_path']).read_text(encoding='utf-8'))
    assert (Path(proof['game_root'])/relative).read_bytes()==original[relative]
    assert 'disabled-list-cleanup' in proof['patches']

def test_unrouted_duplicate_keys_are_inventory_only_and_sdk_output_is_retained(tmp_path):
    source=files();relative='data/AudioList.json'
    source[relative]=b'{"voice":"first","voice":"last"}'
    result=bridge.rewrite_project(source,{'data/Items.json':[{'pointer':'/1/name','source_text':'原文','text':'中文'}]},tmp_path/'work',SDK)
    proof=json.loads(Path(result['sidecar_path']).read_text(encoding='utf-8'))
    assert proof['source_duplicates']==[{'path':relative,'keys':[{'pointer':'/voice','occurrences':2}]}]
    assert result['discovery_only_paths']==[relative]
    assert (Path(proof['game_root'])/relative).read_bytes()==source[relative]
    output=Path(result['output_paths'][relative]);assert json.loads(output.read_bytes())=={'voice':'last'}
    row=next(r for r in proof['rounds'][0]['files'] if r['path']==relative)
    assert row['byte_changed'] and not row['semantic_changed']
    pd=json.loads((Path(proof['game_root']).parent/'program-data.json').read_text(encoding='utf-8'))
    audio=[r for r in pd['rows'] if r['file']=='AudioList.json']
    assert audio and all(not o['whole_string'] and o['pointer'] is None for r in audio for o in r['occurrences'])
    sidecar=json.loads(Path(result['sidecars'][relative]).read_text(encoding='utf-8'));assert sidecar['discovery_only']

def test_duplicate_key_source_cannot_receive_an_approved_write_pointer(tmp_path):
    source=files();source['data/AudioList.json']=b'{"voice":"first","voice":"last"}'
    with pytest.raises(ValueError,match='BACKEND_DUPLICATE_SOURCE_UNSUPPORTED'):
        bridge.rewrite_project(source,{'data/AudioList.json':[{'pointer':'/voice','source_text':'last','text':'REJECT'}]},tmp_path/'work',SDK)
    assert not list(tmp_path.rglob('project-report.json')) and not list(tmp_path.rglob('sidecar.json'))
