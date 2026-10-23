import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
import test_adapter_acceptance as fixtures

from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.JobControl import JobCancelled,request_action
from ModuleFolders.Service.GameProject.JobController import recover_jobs
from ModuleFolders.Service.GameProject.BuildService import file_hash


@pytest.fixture
def validation_case():
    fixture=fixtures.AdapterAcceptance();fixture.setUp()
    fixture.write('Items',[None]+[{'id':i,'name':f'道具{i}','description':'説明'} for i in range(1,151)])
    project=fixture.root.parent/(fixture.root.name+'-validation')
    with GameProjectService.create(fixture.root,project) as service:
        service.extract()
        unit=service.store.units()[0]
        assert service.import_translations({unit.unit_id:'人工锁定译文'})[0].status=='accepted'
        service.store.set_locked(unit.unit_id,True)
        yield service,unit


def cancel_after_first_chunk(service):
    ids=[]
    def cancel(done,total,label):
        if done>=64:
            with ProjectStore(service.store.root) as other:request_action(other,ids[-1],'cancel')
    with pytest.raises(JobCancelled):
        service.validate(progress=cancel,on_job=lambda j:ids.append(j['job_id']))
    return ids[-1]


def test_cancel_resume_reuses_only_verified_units_and_preserves_locks(validation_case):
    from ModuleFolders.Service.GameProject import ValidationService
    service,unit=validation_case
    metadata=service.store.metadata();translation=service.store.translation(unit.unit_id)
    old_job_id=cancel_after_first_chunk(service)
    old=next(j for j in service.store.jobs() if j['job_id']==old_job_id)
    assert old['run_state']=='CANCELLED'
    assert old['checkpoint']==0  # cancellation before progress publication, journal is authoritative
    with patch.object(ValidationService,'_unit_issues',wraps=ValidationService._unit_issues) as inspect:
        report=service.resume_validation(old_job_id)
        assert inspect.call_count==len(service.store.units())-64
    assert report['passed'] and report['reused_units']==64
    assert service.store.metadata()==metadata
    assert service.store.translation(unit.unit_id)==translation
    final=service.store.jobs()[-1]
    assert final['run_state']=='COMPLETED'
    assert json.loads(Path(final['result']['report_path']).read_text(encoding='utf-8'))==report
    assert file_hash(final['result']['report_path'])==final['result']['report_sha256']
    assert next(j for j in service.store.jobs() if j['job_id']==old_job_id)['run_state']=='CANCELLED'


def test_changed_input_refuses_checkpoint_before_reuse(validation_case):
    service,unit=validation_case
    old_job_id=cancel_after_first_chunk(service)
    service.store.set_locked(unit.unit_id,False)
    current=service.store.translation(unit.unit_id)
    assert service.import_translations([{'unit_id':unit.unit_id,'text':'人工新编辑',
        'expected_revision':current['revision']}])[0].status=='accepted'
    count=len(service.store.jobs())
    with pytest.raises(ValueError,match='VALIDATION_RESUME_INPUT_CHANGED'):
        service.resume_validation(old_job_id)
    assert len(service.store.jobs())==count
    assert service.store.translation(unit.unit_id)['text']=='人工新编辑'


def test_frozen_input_tampering_is_rejected_and_retained(validation_case):
    service,unit=validation_case
    old_job_id=cancel_after_first_chunk(service)
    old=next(j for j in service.store.jobs() if j['job_id']==old_job_id)
    snapshot=service.store.root/'validations'/old['result']['validation_id']/'project.sqlite3'
    with snapshot.open('ab') as stream:stream.write(b'injected-corruption')
    corrupted=file_hash(snapshot)
    with pytest.raises(ValueError,match='VALIDATION_FROZEN_INPUT_CHANGED'):
        service.resume_validation(old_job_id)
    assert file_hash(snapshot)==corrupted


def test_actual_process_exit_and_recovery_preserves_committed_checkpoint(validation_case):
    service,unit=validation_case
    before=service.store.translation(unit.unit_id)
    code='''import os,sys
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
with GameProjectService(sys.argv[1]) as service:
    service.validate(progress=lambda done,total,label:os._exit(39) if done>=64 else None)
'''
    result=subprocess.run([sys.executable,'-c',code,str(service.store.root)],
        cwd=Path(__file__).resolve().parents[2],capture_output=True,timeout=20)
    assert result.returncode==39,result.stderr
    old=service.store.jobs()[-1];assert old['operation']=='VALIDATE'
    assert old['run_state']=='RUNNING'
    assert old['job_id'] in recover_jobs(service.store)['interrupted_jobs']
    report=service.resume_validation(old['job_id'])
    assert report['passed'] and report['reused_units']==64
    assert service.store.translation(unit.unit_id)==before


def test_readonly_inspection_does_not_create_jobs_or_files(validation_case):
    service,unit=validation_case
    snapshot=service.store.root/'readonly-check';snapshot.mkdir()
    service.store.snapshot(snapshot/'project.sqlite3')
    before=file_hash(snapshot/'project.sqlite3')
    with ProjectStore(snapshot,readonly=True) as frozen:
        readonly=GameProjectService.__new__(GameProjectService);readonly.store=frozen
        report=readonly.validate()
        assert report['passed']
    assert file_hash(snapshot/'project.sqlite3')==before
    assert {p.name for p in snapshot.iterdir()}=={'project.sqlite3'}


def test_validation_pause_keeps_control_connection_responsive(validation_case):
    import threading,time
    service,unit=validation_case
    root=service.store.root
    entered=threading.Event();release=threading.Event();ids=[];results=[];errors=[]
    def progress(done,total,label):
        if done==64:entered.set();release.wait(5)
    def run():
        try:
            with GameProjectService(root) as other:
                results.append(other.validate(progress=progress,on_job=lambda j:ids.append(j['job_id'])))
        except Exception as exc:errors.append(exc)
    thread=threading.Thread(target=run);thread.start()
    try:
        assert entered.wait(5)
        request_action(service.store,ids[-1],'pause');release.set()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            current=next(j for j in service.store.jobs() if j['job_id']==ids[-1])
            if current['run_state']=='PAUSED':break
            time.sleep(.01)
        assert current['run_state']=='PAUSED'
        assert service.store.translation(unit.unit_id)['manual_locked']
        request_action(service.store,ids[-1],'resume')
        thread.join(5)
        assert not thread.is_alive()
        assert not errors and results[0]['passed']
    finally:
        release.set()
        if thread.is_alive() and ids:
            request_action(service.store,ids[-1],'cancel');thread.join(5)
