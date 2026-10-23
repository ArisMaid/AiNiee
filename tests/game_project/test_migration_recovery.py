import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

import pytest
from ModuleFolders.Service.GameProject.BuildService import file_hash
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.JobControl import JobCancelled,request_action
from ModuleFolders.Service.GameProject.ProjectStore import StoreViolation
from ModuleFolders.Service.GameProject.MigrationWorkflow import prepare_review,apply_review,resume_review


@pytest.fixture
def migration():
    base=Path(__file__).resolve().parents[2]/'work/acceptance';base.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='migration-recovery-',dir=base));source=root/'game'
    (source/'data').mkdir(parents=True);(source/'js').mkdir()
    (source/'index.html').write_text('<script src="js/rpg_core.js"></script>',encoding='utf-8')
    (source/'js/rpg_core.js').write_text('// rpg_core.js v1.6.2',encoding='utf-8')
    (source/'data/System.json').write_text(json.dumps({'gameTitle':'テスト','advanced':{'gameId':901},
        'terms':{'save':'保存','load':'再開','cancel':'中止'}},ensure_ascii=False),encoding='utf-8')
    with GameProjectService.create(source,root/'old') as old,GameProjectService.create(source,root/'new') as new:
        old.extract();new.extract()
        values={'保存':'存档','再開':'读档','中止':'取消'}
        translations={u.unit_id:values[u.source_text] for u in old.store.units() if u.source_text in values}
        assert len(translations)==3
        assert all(r.status=='accepted' for r in old.import_translations(translations))
        plan=prepare_review(old.store.root,new.store.root)
        assert len(plan['plan']['matches'])==3
        yield old,new,plan


def cancel_after_first(old,new,plan):
    jobs=[]
    def progress(done,total,detail):
        if done==1:request_action(new.store,jobs[-1],'cancel')
    with pytest.raises(JobCancelled):
        apply_review(new.store.root,plan['plan_id'],progress=progress,on_job=jobs.append)
    job=next(j for j in new.store.jobs() if j['job_id']==jobs[0])
    assert job['run_state']=='CANCELLED' and job['checkpoint']==0
    assert sum(r['origin']=='migration' for r in new.store.proposals())==1
    return job


def translations(store):return {u.unit_id:store.translation(u.unit_id) for u in store.units()}


def test_resume_closes_commit_progress_gap_and_preserves_later_manual_lock(migration):
    old,new,plan=migration
    before=file_hash(old.store.root/'project.sqlite3');wal=old.store.root/'project.sqlite3-wal'
    wal_before=file_hash(wal) if wal.exists() else None
    prior=cancel_after_first(old,new,plan);first=plan['plan']['matches'][0]['new_unit_id']
    assert new.import_translations({first:'人工保留'})[0].status=='accepted'
    new.store.set_locked(first,True);manual=new.store.translation(first)
    result=resume_review(new.store.root,prior['job_id'])
    assert result['accepted']==3 and result['reused_units']==1 and result['new_units']==2
    assert new.store.translation(first)==manual
    assert sum(r['origin']=='migration' for r in new.store.proposals())==3
    assert next(j for j in new.store.jobs() if j['job_id']==prior['job_id'])['run_state']=='CANCELLED'
    assert next(j for j in new.store.jobs() if j['job_id']==result['job_id'])['run_state']=='COMPLETED'
    assert file_hash(old.store.root/'project.sqlite3')==before
    if wal_before is not None:assert file_hash(wal)==wal_before


def test_pending_edit_or_lock_rejects_before_any_remaining_write(migration):
    old,new,plan=migration;prior=cancel_after_first(old,new,plan)
    pending=plan['plan']['matches'][1]['new_unit_id']
    new.import_translations({pending:'手动新稿'});new.store.set_locked(pending,True)
    before=translations(new.store)
    with pytest.raises(ValueError,match='MIGRATION_PLAN_STALE'):resume_review(new.store.root,prior['job_id'])
    assert translations(new.store)==before
    assert sum(r['origin']=='migration' for r in new.store.proposals())==1


def test_source_revision_change_refuses_resume_without_target_mutation(migration):
    old,new,plan=migration;prior=cancel_after_first(old,new,plan)
    uid=plan['plan']['matches'][0]['old_unit_id'];old.import_translations({uid:'旧工程新修订'})
    before=translations(new.store)
    with pytest.raises(ValueError,match='MIGRATION_RESUME_INPUT_CHANGED'):resume_review(new.store.root,prior['job_id'])
    assert translations(new.store)==before


def test_target_profile_change_refuses_resume(migration):
    old,new,plan=migration;prior=cancel_after_first(old,new,plan)
    new.store.update_metadata({'profile_hash':'b'*64})
    before=translations(new.store)
    with pytest.raises(ValueError,match='MIGRATION_RESUME_INPUT_CHANGED'):resume_review(new.store.root,prior['job_id'])
    assert translations(new.store)==before


def test_frozen_inputs_and_receipt_corruption_are_retained_and_rejected(migration):
    old,new,plan=migration;prior=cancel_after_first(old,new,plan)
    path=new.store.root/prior['payload']['inputs_path'];original=path.read_bytes()
    path.write_bytes(b'{}')
    with pytest.raises(ValueError,match='MIGRATION_FROZEN_INPUT_CHANGED'):resume_review(new.store.root,prior['job_id'])
    assert path.read_bytes()==b'{}';path.write_bytes(original)
    with sqlite3.connect(new.store.root/'project.sqlite3') as db:
        db.execute("UPDATE proposals SET expected_revision=99 WHERE origin='migration'")
    with pytest.raises(ValueError,match='MIGRATION_LEDGER_INVALID'):resume_review(new.store.root,prior['job_id'])
    assert sum(r['origin']=='migration' for r in new.store.proposals())==1


def test_pause_stops_between_commits_and_live_resume_continues_same_attempt(migration):
    old,new,plan=migration;jobs=[];results=[];errors=[]
    def progress(done,total,detail):
        if done==1:request_action(new.store,jobs[-1],'pause')
    def execute():
        try:results.append(apply_review(new.store.root,plan['plan_id'],progress=progress,on_job=jobs.append))
        except BaseException as error:errors.append(error)
    thread=threading.Thread(target=execute);thread.start()
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if jobs and next(j for j in new.store.jobs() if j['job_id']==jobs[-1])['run_state']=='PAUSED':break
            if not thread.is_alive():break
            time.sleep(.02)
        assert jobs and next(j for j in new.store.jobs() if j['job_id']==jobs[-1])['run_state']=='PAUSED'
        assert sum(r['origin']=='migration' for r in new.store.proposals())==1
        time.sleep(.12)
        assert sum(r['origin']=='migration' for r in new.store.proposals())==1
        request_action(new.store,jobs[-1],'resume');thread.join(10)
        assert not thread.is_alive() and not errors and results[0]['accepted']==3
    finally:
        if thread.is_alive():
            request_action(new.store,jobs[-1],'cancel');thread.join(10)


def test_registry_and_completion_rollback_together_then_reuse_all_receipts(migration):
    old,new,plan=migration
    with sqlite3.connect(new.store.root/'project.sqlite3') as db:
        db.execute("CREATE TRIGGER fail_migration_completion BEFORE UPDATE ON jobs WHEN NEW.operation='MIGRATE' AND NEW.run_state='COMPLETED' BEGIN SELECT RAISE(ABORT,'completion fault'); END")
    with pytest.raises(StoreViolation,match='completion fault'):apply_review(new.store.root,plan['plan_id'])
    prior=next(j for j in new.store.jobs() if j['operation']=='MIGRATE')
    assert prior['run_state']=='FAILED'
    assert new.store.metadata()['migration_reviews'][plan['plan_id']]['state']=='planned'
    with sqlite3.connect(new.store.root/'project.sqlite3') as db:db.execute('DROP TRIGGER fail_migration_completion')
    result=resume_review(new.store.root,prior['job_id'])
    assert result['reused_units']==3 and result['new_units']==0
    assert sum(r['origin']=='migration' for r in new.store.proposals())==3


def test_real_process_death_after_commit_reuses_receipt_via_cli(migration):
    old,new,plan=migration;root=Path(__file__).resolve().parents[2]
    code="""import os,sys
from ModuleFolders.Service.GameProject.MigrationWorkflow import apply_review
def progress(done,total,detail):
    if done==1:os._exit(41)
apply_review(sys.argv[1],sys.argv[2],progress=progress)
"""
    run=subprocess.run([sys.executable,'-c',code,str(new.store.root),plan['plan_id']],cwd=root,capture_output=True,timeout=20)
    assert run.returncode==41,run.stderr
    prior=next(j for j in new.store.jobs() if j['operation']=='MIGRATE')
    assert prior['run_state']=='RUNNING' and prior['checkpoint']==0
    resumed=subprocess.run([sys.executable,'RpgApp.py','--cli','resume-migration','--project',str(new.store.root),
        '--job-id',prior['job_id']],cwd=root,capture_output=True,timeout=20)
    assert resumed.returncode==0,resumed.stderr
    result=json.loads(resumed.stdout.decode('utf-8'));assert result['reused_units']==1 and result['new_units']==2
    assert next(j for j in new.store.jobs() if j['job_id']==prior['job_id'])['run_state']=='INTERRUPTED'


def test_real_process_death_after_atomic_completion_stays_completed(migration):
    old,new,plan=migration;root=Path(__file__).resolve().parents[2]
    code="""import os,sys
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.MigrationWorkflow import apply_review
original=ProjectStore.complete_migration_review
def completed(self,*args,**kwargs):
    original(self,*args,**kwargs)
    os._exit(42)
ProjectStore.complete_migration_review=completed
apply_review(sys.argv[1],sys.argv[2])
"""
    run=subprocess.run([sys.executable,'-c',code,str(new.store.root),plan['plan_id']],cwd=root,capture_output=True,timeout=20)
    assert run.returncode==42,run.stderr
    job=next(j for j in new.store.jobs() if j['operation']=='MIGRATE')
    assert job['run_state']=='COMPLETED' and job['result']['accepted']==3
    assert new.store.metadata()['migration_reviews'][plan['plan_id']]['state']=='applied'
    with pytest.raises(ValueError,match='MIGRATION_REVIEW_ALREADY_APPLIED'):resume_review(new.store.root,job['job_id'])
    assert sum(r['origin']=='migration' for r in new.store.proposals())==3
