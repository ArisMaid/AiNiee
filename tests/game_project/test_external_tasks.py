"""Codex acceptance for one-shot external job publication and controls."""
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

from PIL import Image
import pytest
import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.JobControl import JobCancelled,request_action
from ModuleFolders.Service.GameProject.ProjectLock import JobLease,ProjectLock
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Infrastructure.Platform.OwnedProcess import run


@pytest.fixture
def project():
    fixture=fixtures.AdapterAcceptance();fixture.setUp()
    root=fixture.root
    (root/'img').mkdir();out=io.BytesIO();Image.new('RGB',(100,60),'white').save(out,format='PNG')
    (root/'img/text.png').write_bytes(out.getvalue())
    with GameProjectService.create(root,root.parent/(root.name+'-external-task')) as service:
        service.extract();yield service


def wait_for(predicate,timeout=6):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.01)
    raise AssertionError('external task did not reach expected state')


def test_pause_cancel_before_compute_and_locks_are_released(project):
    from ModuleFolders.Service.GameProject.ExternalTask import run_external_task
    ids=[];errors=[];computed=[];published=[]
    def on_job(job):ids.append(job['job_id']);request_action(project.store,ids[0],'pause')
    def work():
        try:run_external_task(project.store,'ONCE_TEST',{},lambda c:computed.append(True),lambda v:published.append(True),on_job)
        except BaseException as error:errors.append(error)
    thread=threading.Thread(target=work);thread.start()
    try:
        wait_for(lambda:ids and project.store.jobs()[-1]['run_state']=='PAUSED')
        with pytest.raises(ValueError,match='PROJECT_BUSY'):
            with JobLease(project.store.root,ids[0]):pass
        request_action(project.store,ids[0],'cancel');thread.join(5)
        assert not thread.is_alive() and len(errors)==1 and isinstance(errors[0],JobCancelled)
        assert not computed and not published and project.store.jobs()[-1]['run_state']=='CANCELLED'
        with ProjectLock(project.store.root),JobLease(project.store.root,ids[0]):pass
    finally:
        if thread.is_alive():request_action(project.store,ids[0],'cancel');thread.join(5)


def test_success_and_commit_phase_reject_late_cancel(project):
    from ModuleFolders.Service.GameProject.ExternalTask import run_external_task
    ids=[]
    def publish(value):
        assert value=='computed'
        with pytest.raises(ValueError,match='JOB_ACTION_REFUSED'):request_action(project.store,ids[0],'cancel')
        return {'passed':True}
    result=run_external_task(project.store,'ONCE_TEST',{},lambda c:'computed',publish,lambda j:ids.append(j['job_id']))
    job=project.store.jobs()[-1]
    assert result=={'passed':True,'job_id':ids[0]}
    assert job['run_state']=='COMPLETED' and job['checkpoint']==1 and job['result']['passed']


def test_compute_and_publish_errors_preserve_the_original(project):
    from ModuleFolders.Service.GameProject.ExternalTask import run_external_task
    for phase in ('compute','publish'):
        error=RuntimeError('injected '+phase)
        def fail(*args):raise error
        with pytest.raises(RuntimeError,match='injected') as caught:
            run_external_task(project.store,'ONCE_TEST',{},fail if phase=='compute' else lambda c:None,
                fail if phase=='publish' else lambda v:{})
        assert caught.value is error and project.store.jobs()[-1]['run_state']=='FAILED'


def test_ocr_cancels_actual_owned_process_and_does_not_save_candidate(project):
    from ModuleFolders.Service.GameProject import ImageService
    root=project.store.root;ready=root/'ocr-owned-ready';ids=[];errors=[]
    def controlled_ocr(*args):
        env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP'}}
        code='import sys,time;from pathlib import Path;Path(sys.argv[1]).write_text("ready");time.sleep(300)'
        run([sys._base_executable,'-u','-c',code,str(ready)],cwd=root,env=env,timeout=15)
        raise AssertionError('cancelled process cannot yield an OCR candidate')
    def work():
        try:ImageService.ocr(project.store,'img/text.png','unused','unused',on_job=lambda j:ids.append(j['job_id']))
        except BaseException as error:errors.append(error)
    with patch('ModuleFolders.Service.GameProject.ImageCodec.ocr_png',side_effect=controlled_ocr):
        thread=threading.Thread(target=work);thread.start()
        try:
            wait_for(lambda:ready.exists() and ids)
            request_action(project.store,ids[0],'pause');time.sleep(.15)
            assert project.store.jobs()[-1]['run_state']=='PAUSE_REQUESTED'
            request_action(project.store,ids[0],'cancel');thread.join(5)
            assert not thread.is_alive() and len(errors)==1 and isinstance(errors[0],JobCancelled)
            assert project.store.jobs()[-1]['run_state']=='CANCELLED'
            assert not list((root/'images/ocr').glob('*.json'))
        finally:
            if thread.is_alive():request_action(project.store,ids[0],'cancel');thread.join(5)


def test_ocr_pause_then_resume_saves_one_candidate(project):
    from ModuleFolders.Service.GameProject import ImageService
    ids=[];results=[];errors=[]
    def on_job(job):ids.append(job['job_id'])
    def controlled_ocr(*args):
        request_action(project.store,ids[0],'pause')
        return {'regions':[]}
    def work():
        try:results.append(ImageService.ocr(project.store,'img/text.png','unused','unused',on_job=on_job))
        except BaseException as error:errors.append(error)
    with patch('ModuleFolders.Service.GameProject.ImageCodec.ocr_png',side_effect=controlled_ocr):
        thread=threading.Thread(target=work);thread.start()
        try:
            wait_for(lambda:ids and project.store.jobs()[-1]['run_state']=='PAUSED')
            assert not list((project.store.root/'images/ocr').glob('*.json'))
            request_action(project.store,ids[0],'resume');thread.join(5)
            assert not thread.is_alive() and not errors and len(results)==1
            assert Path(results[0]['candidate_file']).is_file()
            assert project.store.jobs()[-1]['run_state']=='COMPLETED'
        finally:
            if thread.is_alive():request_action(project.store,ids[0],'cancel');thread.join(5)


def test_backend_candidate_rejects_edits_during_worker_execution(project):
    from ModuleFolders.Service.GameProject.BackendCandidateService import generate_candidate
    item=next(u for u in project.store.units() if u.source_text=='回復薬')
    project.import_translations({item.unit_id:'恢复药'})
    def rewrite(backend,relative,original,changes,*args):
        # Model commits own an execution lease and use the SQLite committer;
        # unlike manual UI import they need not acquire ProjectLock here.
        from ModuleFolders.Service.GameProject.TranslationCommitter import TranslationCommitter
        from ModuleFolders.Domain.GameProject.Models import TranslationProposal
        current=project.store.translation(item.unit_id)
        result=TranslationCommitter(project.store).submit(TranslationProposal(item.unit_id,
            '新人工译文',item.source_hash,current['revision'],origin='manual'))
        assert result.status=='accepted'
        data=json.loads(original);data[1]['name']='恢复药'
        return {'output_bytes':json.dumps(data,ensure_ascii=False).encode(),
            'sidecar_path':'unused','capabilities':{}}
    with patch('ModuleFolders.Service.GameProject.BackendCandidateService.rewrite_document',side_effect=rewrite):
        with pytest.raises(ValueError,match='BACKEND_CANDIDATE_INPUT_CHANGED'):
            generate_candidate(project.store,'stev',Path(__file__).resolve().parents[2]/'StevExtraction','data/Items.json')
    assert project.store.translation(item.unit_id)['text']=='新人工译文'
    assert project.store.jobs()[-1]['run_state']=='FAILED'
    assert not list((project.store.root/'work/candidates').glob('*'))
