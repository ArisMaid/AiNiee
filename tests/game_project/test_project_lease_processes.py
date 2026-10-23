"""Real owned Windows processes, model lease lifetime and independent Qt readers."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
import pytest

from ModuleFolders.Domain.GameProject.Models import Occurrence,TranslationUnit,TranslationProposal,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.ProjectLock import ProjectLock,JobLease
from ModuleFolders.Service.GameProject.JobControl import request_action
from ModuleFolders.Service.GameProject.JobController import recover_jobs

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Native Windows process/lease acceptance')
ROOT=Path(__file__).resolve().parents[2]

CHILD=r'''
import json,sys,time
from pathlib import Path
from types import SimpleNamespace
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner
from ModuleFolders.Service.GameProject.PathGuard import atomic_write
from ModuleFolders.Base.Base import Base
root,case,mode=map(Path,sys.argv[1:]);mode=str(mode)
Base.work_status=Base.STATUS.TASKING
def save(name,value):atomic_write(case/name,json.dumps(value,ensure_ascii=False).encode('utf-8'))
with ProjectStore(root) as store:items=[i for i in build_projection(store).items_iter() if i.get_extra('unit_id')=='u0']
config=SimpleNamespace(request_timeout=10,project_terms_data=[],get_active_platform_configuration=lambda:{'provider':'synthetic-only'})
class Requester:
    def sent_request(self,*args):
        save('request.json',{'requester':'synthetic-only'})
        until=time.monotonic()+25
        while not (case/'release').exists():
            if time.monotonic()>until:raise RuntimeError('fixture release timeout')
            time.sleep(.01)
        return mode=='finish','',json.dumps({'u0':'租约译文'}),2,2
try:
    result=GameBatchRunner(items,config).run(Requester(),on_job=lambda j:save('job.json',j))
    save('result.json',{'result':result})
except Exception as error:
    save('result.json',{'error':str(error),'type':type(error).__name__})
'''


def wait_for(predicate,process=None,pump=None,seconds=12):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        if pump:pump()
        value=predicate()
        if value:return value
        if process is not None and process.poll() is not None:
            raise AssertionError('owned fixture exited before readiness')
        time.sleep(.01)
    raise AssertionError('native lease fixture readiness timed out')


@pytest.fixture
def store(tmp_path):
    with ProjectStore.create(tmp_path/'工程 空格',{'project_id':'native-model-lease',
            'engine':'rpgmaker-mz','source_root':str(tmp_path/'source')}) as connection:
        connection.replace_units([TranslationUnit('u0','menu','保存',occurrences=(
            Occurrence('o0','data/System.json',{'pointer':'/terms/save'},hash_text('保存')),))])
        yield connection


@contextmanager
def owner(store,case,mode='normal'):
    from ModuleFolders.Infrastructure.Platform.WindowsJob import WindowsJob
    from ModuleFolders.Infrastructure.Platform.WindowsProcess import WindowsProcess
    case.mkdir();script=case/'owner.py';script.write_text(CHILD,encoding='utf-8')
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP','PATH','COMSPEC'} and v}
    env.update(PYTHONPATH=str(ROOT),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
    with WindowsJob() as job,WindowsProcess([sys.executable,str(script),str(store.root),str(case),mode],
            cwd=case,env=env,job=job) as process:
        process.stdin.close()
        try:
            wait_for(lambda:(case/'job.json').exists() and (case/'request.json').exists(),process)
            identity=json.loads((case/'job.json').read_text(encoding='utf-8'))['job_id']
            yield process,job,identity
        finally:
            if process.poll() is None:job.terminate(79)
            process.wait(5)
            (case/'stdout.log').write_bytes(process.stdout.read())
            (case/'stderr.log').write_bytes(process.stderr.read())


@pytest.mark.parametrize('paused',[False,True])
def test_dead_native_model_owner_recovers_its_stage_and_retained_response(store,tmp_path,paused):
    case=tmp_path/'crash'
    with owner(store,case) as (process,job,identity):
        if paused:
            request_action(store,identity,'pause');(case/'release').touch()
            wait_for(lambda:store.get_job(identity)['run_state']=='PAUSED',process)
        before=store.get_job(identity)
        assert recover_jobs(store)['active_jobs']==[identity]
        job.terminate(77);assert process.wait(5)==77
        assert recover_jobs(store)['interrupted_jobs']==[identity]
        after=store.get_job(identity)
        assert after['run_state']=='INTERRUPTED'
        for field in ('stage','checkpoint','payload','result'):assert after[field]==before[field]
        assert not recover_jobs(store)['interrupted_jobs']
        with ProjectLock(store.root),JobLease(store.root,identity):pass


def test_real_owner_finishes_failed_between_enumeration_and_lease_probe(store,tmp_path):
    case=tmp_path/'finish'
    with owner(store,case,'finish') as (process,job,identity):
        original=store.active_job_summaries;captured=[]
        def enumerate_then_finish(job_id=None):
            rows=original(job_id);captured.extend(rows)
            (case/'release').touch();assert process.wait(8)==0
            return rows
        with patch.object(store,'active_job_summaries',side_effect=enumerate_then_finish):
            result=recover_jobs(store)
        assert captured[0]['run_state']=='RUNNING' and not result['interrupted_jobs'] and not result['active_jobs']
        final=store.get_job(identity)
        assert final['run_state']=='FAILED' and 'MODEL_REQUEST_FAILED' in final['error']
        assert final['result']['response_text'] and store.translation('u0') is None


def test_two_gui_readers_open_during_paused_model_and_manual_lock_survives_resume(store,tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
    configure_qt_paths()
    from PyQt5.QtWidgets import QApplication
    from UserInterface.GameProject.GameProjectPage import GameProjectPage
    app=QApplication.instance() or QApplication([]);pages=[]
    case=tmp_path/'gui-readers'
    with owner(store,case) as (process,job,identity):
        try:
            request_action(store,identity,'pause');(case/'release').touch()
            wait_for(lambda:store.get_job(identity)['run_state']=='PAUSED',process)
            for _ in range(2):
                page=GameProjectPage();pages.append(page);page.show();assert page.set_project(store.root)
                wait_for(lambda:not page.is_busy(),process,app.processEvents)
                assert not page.error_label.text() and page.unit_model.rowCount()==1
            assert recover_jobs(store)['active_jobs']==[identity]
            with ProjectLock(store.root):
                accepted=store.commit(TranslationProposal('u0','人工保留',hash_text('保存')))
                assert accepted.status=='accepted';store.set_locked('u0',True)
            request_action(store,identity,'resume');assert process.wait(8)==0
            result=json.loads((case/'result.json').read_text(encoding='utf-8'))['result']
            assert not result['check_result'] and result['row_count']==0
            assert store.translation('u0')['text']=='人工保留' and store.translation('u0')['manual_locked']
            assert not recover_jobs(store)['interrupted_jobs']
            for page in pages:
                assert page._start_job('refresh',{})
                wait_for(lambda:not page.is_busy(),pump=app.processEvents)
                assert page.unit_model.rowCount()==1
        finally:
            for page in pages:
                if page.is_busy():wait_for(lambda:not page.is_busy(),pump=app.processEvents,seconds=8)
                page.close();page.deleteLater()
            app.processEvents()


def test_finishing_busy_lease_is_not_reported_as_an_active_job(store):
    identity=store.create_job('FINISHING')['job_id'];store.update_job(identity,run_state='RUNNING')
    from ModuleFolders.Service.GameProject import JobController
    class FinishingBusy:
        def __init__(self,*args):pass
        def __enter__(self):
            store.update_job(identity,run_state='FAILED',error='retained')
            raise ValueError('PROJECT_BUSY: finishing owner still holds handle')
        def __exit__(self,*args):pass
    with patch.object(JobController,'JobLease',FinishingBusy):result=recover_jobs(store)
    assert not result['active_jobs'] and not result['interrupted_jobs']
    assert store.get_job(identity)['error']=='retained'
