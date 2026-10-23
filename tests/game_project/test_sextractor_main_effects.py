"""Actual main-entry effect, cancellation and configuration boundaries."""
import hashlib,json,os,shutil,threading,time
from pathlib import Path
import pytest

SDK=Path(__file__).resolve().parents[2]/'work/vendor/SExtractor'
pytestmark=pytest.mark.skipif(not (SDK/'src/main_extract.py').is_file(),reason='Pinned optional SExtractor is not installed')
NAMES=('main_extract.py','main_extract_json.py','main_extract_part.py','var_extract.py','common.py',
    'helper_text.py','helper_read.py','helper_write.py','extract_TXT.py','extract_RPGMV.py','engine.ini')

def copy_sdk(tmp_path):
    sdk=tmp_path/'sdk';(sdk/'src').mkdir(parents=True)
    for name in NAMES:shutil.copy2(SDK/'src'/name,sdk/'src'/name)
    return sdk

def raw_source():
    return b'\xef\xbb\xbf'+json.dumps({'name':'原文'},ensure_ascii=False,indent=2).replace('\n','\r\n').encode()

def changes():return [{'pointer':'/name','source_text':'原文','text':'译文'}]

def test_os_open_truncation_of_seed_is_denied_before_modification(tmp_path):
    from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import rewrite_document
    sdk=copy_sdk(tmp_path)
    with (sdk/'src/main_extract.py').open('a',encoding='utf-8') as handle:
        handle.write('\n_real_main = mainExtract\ndef mainExtract(args, initDone=None):\n'
            '    descriptor = os.open(os.path.join(args["workpath"],"input.json"),os.O_WRONLY|os.O_TRUNC)\n'
            '    os.write(descriptor,b"bad"); os.close(descriptor)\n'
            '    return _real_main(args,initDone)\n')
    with pytest.raises(ValueError,match='BACKEND_SIDE_EFFECT: open'):
        rewrite_document('sextractor','data/Items.json',raw_source(),changes(),tmp_path/'work',sdk)
    seeded=list((tmp_path/'work').rglob('document/input.json'))
    assert seeded and all(path.read_bytes()==raw_source() for path in seeded)

def test_cancel_while_actual_import_is_writing_retains_partial_without_publication(tmp_path):
    from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import rewrite_document
    from ModuleFolders.Infrastructure.Platform.OwnedProcess import worker_control
    from ModuleFolders.Service.GameProject.JobControl import JobCancelled
    sdk=copy_sdk(tmp_path)
    with (sdk/'src/main_extract.py').open('a',encoding='utf-8') as handle:
        handle.write('\n_real_main = mainExtract\ndef mainExtract(args, initDone=None):\n'
            '    if not args.get("noInput"):\n'
            '        with open(os.path.join(args["workpath"],"new","input.json"),"wb") as output: output.write(b"PARTIAL")\n'
            '        import time; time.sleep(30)\n'
            '    return _real_main(args,initDone)\n')
    cancel=threading.Event();started=threading.Event();stop=threading.Event();work=tmp_path/'work'
    def monitor():
        deadline=time.monotonic()+10
        while not stop.is_set() and time.monotonic()<deadline:
            for path in work.glob('*/import/main/document/new/input.json'):
                if path.read_bytes()==b'PARTIAL':started.set();cancel.set();return
            time.sleep(.01)
    def check():
        if cancel.is_set():raise JobCancelled('controlled real import cancellation')
    thread=threading.Thread(target=monitor,daemon=True);thread.start();start=time.monotonic()
    try:
        with worker_control(check,'real-main-import-cancel'):
            with pytest.raises(JobCancelled):rewrite_document('sextractor','data/Items.json',raw_source(),changes(),work,sdk)
    finally:stop.set();thread.join(timeout=2)
    assert started.is_set() and time.monotonic()-start<12
    assert not list(work.glob('*/sidecar.json'))
    assert [p.read_bytes() for p in work.glob('*/import/main/document/new/input.json')]==[b'PARTIAL']
    assert all(p.read_bytes()==raw_source() for p in work.rglob('document/input.json'))

def test_engine_ini_change_invalidates_a_real_configured_route_before_build(tmp_path):
    from ModuleFolders.Service.GameProject.BackendRoutes import fingerprint,configure_route
    from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
    sdk=copy_sdk(tmp_path);source=tmp_path/'source';(source/'data').mkdir(parents=True);(source/'js').mkdir()
    (source/'index.html').write_text('<script src="js/rmmz_core.js"></script>',encoding='utf-8')
    (source/'js/rmmz_core.js').write_text('// rmmz_core.js v1.7.0',encoding='utf-8')
    (source/'data/System.json').write_text(json.dumps({'gameTitle':'テスト','advanced':{'gameId':1}}),encoding='utf-8')
    (source/'data/Items.json').write_text(json.dumps([None,{'id':1,'name':'回復薬','description':'説明','note':''}]),encoding='utf-8')
    originals={p:p.read_bytes() for p in source.rglob('*') if p.is_file()}
    with GameProjectService.create(source,tmp_path/'project') as service:
        service.extract();unit=next(u for u in service.store.units() if u.source_text=='回復薬')
        service.import_translations({unit.unit_id:'恢复药'})
        configured=configure_route(service.store,'data/Items.json','sextractor',sdk)
        before=fingerprint(sdk);assert 'src/engine.ini' in before['files']
        assert configured['fingerprint']==before['digest']
        with (sdk/'src/engine.ini').open('a',encoding='utf-8') as handle:handle.write('\n; config pin acceptance\n')
        after=fingerprint(sdk)
        assert before['digest']!=after['digest'] and before['files']['src/engine.ini']!=after['files']['src/engine.ini']
        with pytest.raises(ValueError,match='BACKEND_SOURCE_CHANGED'):service.build(tmp_path/'outputs',test=True)
        assert not list((tmp_path/'outputs').glob('game-zh-CN-*'))
    assert all(path.read_bytes()==value for path,value in originals.items())

def test_actual_socket_creation_stays_denied_without_a_connection_attempt(tmp_path):
    from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import rewrite_document
    sdk=copy_sdk(tmp_path)
    with (sdk/'src/main_extract.py').open('a',encoding='utf-8') as handle:
        handle.write('\n_real_main = mainExtract\ndef mainExtract(args, initDone=None):\n'
            '    import socket\n'
            '    with socket.socket(): pass\n'
            '    return _real_main(args,initDone)\n')
    with pytest.raises(ValueError,match=r'BACKEND_SIDE_EFFECT: socket\.__new__'):
        rewrite_document('sextractor','data/Items.json',raw_source(),changes(),tmp_path/'work',sdk)
    assert not list((tmp_path/'work').glob('*/sidecar.json'))

def test_request_persistence_failure_does_not_start_the_backend(tmp_path):
    from unittest.mock import patch
    from ModuleFolders.Infrastructure.GameAdapters import SExtractorMainBridge as main
    from ModuleFolders.Infrastructure.GameAdapters import CompatibilityBridge as bridge
    with patch.object(main,'atomic_write',side_effect=OSError('controlled evidence-write failure')):
        with patch.object(bridge,'_run_worker') as run:
            with pytest.raises(OSError,match='controlled evidence-write failure'):
                bridge.rewrite_document('sextractor','data/Items.json',raw_source(),changes(),tmp_path/'work',SDK)
    run.assert_not_called()
    assert not list((tmp_path/'work').rglob('main/document/input.json'))
