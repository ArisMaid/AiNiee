"""Protected acceptance: no stale recovery writes and no historical result decode."""
from unittest.mock import patch
import pytest
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore,StoreViolation
from ModuleFolders.Service.GameProject import JobController
from ModuleFolders.Service.GameProject.ProjectLock import JobLease,ProjectLock


@pytest.fixture
def store(tmp_path):
    with ProjectStore.create(tmp_path/'工程 空格',{'project_id':'recovery-race','engine':'rpgmaker-mz',
            'source_root':str(tmp_path/'source')}) as connection:
        yield connection


def running(store,operation='TEST'):
    job=store.create_job(operation,{'preserved':True})
    store.update_job(job['job_id'],run_state='RUNNING',stage='work',checkpoint=3,
        result={'response_text':'retained response'})
    return job['job_id']


@pytest.mark.parametrize('terminal',['COMPLETED','FAILED','CANCELLED'])
def test_recovery_rechecks_state_after_obtaining_the_lease(store,terminal):
    job_id=running(store)
    class FinishingLease:
        def __init__(self,root,identity):
            self.identity=identity;self.inner=JobLease(root,identity)
        def __enter__(self):
            self.inner.__enter__()
            # The execution owner finished between enumeration and lease
            # acquisition. Its terminal fields must survive recovery intact.
            store.update_job(self.identity,run_state=terminal,stage='owner-finished',
                checkpoint=9,error='owner diagnostic',result={'response_text':'final response'})
            return self
        def __exit__(self,*args):return self.inner.__exit__(*args)
    with patch.object(JobController,'JobLease',FinishingLease):
        result=JobController.recover_jobs(store)
    assert result['interrupted_jobs']==[] and result['active_jobs']==[]
    row=store.get_job(job_id)
    assert (row['run_state'],row['stage'],row['checkpoint'],row['error'],row['result'])==(
        terminal,'owner-finished',9,'owner diagnostic',{'response_text':'final response'})


def test_recovery_only_enumerates_compact_active_summaries(store):
    old=running(store,'HISTORY')
    store.update_job(old,run_state='COMPLETED',result={'large':'x'*(2*1024*1024)})
    current=running(store,'CURRENT')
    store.update_job(current,result={'large':'y'*(2*1024*1024)})
    baseline=store.metadata()
    with (patch.object(store,'jobs',side_effect=AssertionError('no historical enumeration')),
          patch.object(store,'get_job',side_effect=AssertionError('no full job JSON decode'))):
        rows=store.active_job_summaries()
        assert rows==[{'job_id':current,'operation':'CURRENT','run_state':'RUNNING','stage':'work','checkpoint':3}]
        assert store.active_job_summaries(old)==[]
        result=JobController.recover_jobs(store)
        assert result['interrupted_jobs']==[current] and not result['active_jobs']
    assert store.metadata()['content_revision']==baseline['content_revision']
    assert store.get_job(old)['run_state']=='COMPLETED'
    assert store.get_job(current)['result']=={'large':'y'*(2*1024*1024)}


@pytest.mark.parametrize('state',['RUNNING','PAUSED','PAUSE_REQUESTED','CANCEL_REQUESTED','COMMITTING'])
def test_live_owner_is_skipped_and_dead_owner_is_interrupted_without_changing_checkpoint(store,state):
    job_id=running(store)
    if state!='RUNNING':store.update_job(job_id,run_state=state)
    with JobLease(store.root,job_id):
        result=JobController.recover_jobs(store)
        assert result['active_jobs']==[job_id] and result['interrupted_jobs']==[]
        assert store.get_job(job_id)['run_state']==state
    result=JobController.recover_jobs(store)
    assert result['interrupted_jobs']==[job_id] and not result['active_jobs']
    row=store.get_job(job_id)
    assert row['run_state']=='INTERRUPTED' and row['stage']=='work' and row['checkpoint']==3
    assert row['result']=={'response_text':'retained response'}
    assert not JobController.recover_jobs(store)['interrupted_jobs']


def test_project_writer_cannot_be_preempted_by_recovery(store):
    job_id=running(store)
    with ProjectLock(store.root):
        with pytest.raises(ValueError,match='PROJECT_BUSY'):JobController.recover_jobs(store)
    assert store.get_job(job_id)['run_state']=='RUNNING'


def test_conditional_interrupt_never_overwrites_terminal_or_unknown_job(store):
    job_id=running(store)
    store.update_job(job_id,run_state='COMPLETED',error='keep',checkpoint=7)
    before=store.get_job(job_id)
    assert not store.interrupt_job_if_active(job_id,error='new error')
    assert not store.interrupt_job_if_active('unknown',error='new error')
    assert store.get_job(job_id)==before
    assert store.active_job_summaries()==[]


def test_recovery_conditional_write_obeys_readonly_and_live_schema_gate(store,tmp_path):
    job_id=running(store)
    frozen=tmp_path/'frozen/project.sqlite3';store.snapshot(frozen)
    with ProjectStore(frozen.parent,readonly=True) as readonly:
        assert readonly.active_job_summaries()[0]['job_id']==job_id
        with pytest.raises(StoreViolation):readonly.interrupt_job_if_active(job_id,error='must refuse')
    import sqlite3
    with sqlite3.connect(store.root/'project.sqlite3') as other:
        other.execute("UPDATE metadata SET value='99' WHERE key='schema_version'")
    with pytest.raises(StoreViolation):store.interrupt_job_if_active(job_id,error='must refuse')
    with sqlite3.connect(store.root/'project.sqlite3') as other:
        assert other.execute('SELECT run_state FROM jobs WHERE job_id=?',(job_id,)).fetchone()[0]=='RUNNING'
