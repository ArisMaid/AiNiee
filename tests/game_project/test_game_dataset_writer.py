"""A model request epoch is checked in every row writer transaction."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json,threading
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner
from test_game_batch_preparation import create,config,Requester
from ModuleFolders.Domain.GameProject.Models import TranslationProposal

def model_job(store,**changes):
    payload={'unit_ids':['u0'],'dataset_revision':store.metadata()['dataset_revision'],
        'project_id':store.metadata()['project_id'],**changes}
    job=store.create_job('TRANSLATE',payload)
    store.update_job(job['job_id'],run_state='RUNNING')
    store.update_job(job['job_id'],run_state='COMMITTING')
    return job

def test_second_response_row_must_not_accept_after_dataset_changes(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,units,items=create(tmp_path);real_commit=ProjectStore.commit;changed=[]
    batch=GameBatchRunner(items[:2],config())
    def mutate_before_second(self,proposal,*args,**kwargs):
        if proposal.unit_id=='u1' and proposal.origin=='translate' and not changed:
            with ProjectStore(store.root) as concurrent:
                concurrent.replace_units([units[0],replace(units[1],scene_id='changed-context'),*units[2:]])
                changed.append(concurrent.metadata()['dataset_revision'])
        return real_commit(self,proposal,*args,**kwargs)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(ProjectStore,'commit',mutate_before_second)
            result=batch.run(Requester())
        assert changed and changed[0]>batch.dataset_revision
        assert store.translation('u0') is not None
        assert store.translation('u1') is None
        assert not result['check_result']
    finally:store.close()


@pytest.mark.parametrize('dataset',[None,True,'1',-1])
def test_model_job_with_invalid_epoch_cannot_replace_accepted_text(tmp_path,dataset):
    store,units,_=create(tmp_path)
    try:
        store.commit(TranslationProposal('u0','人工原稿',units[0].source_hash,origin='manual'))
        before=store.translation('u0');content=store.metadata()['content_revision']
        job=model_job(store,dataset_revision=dataset)
        result=store.commit(TranslationProposal('u0','模型新稿',units[0].source_hash,before['revision'],
            job_id=job['job_id'],request_item_id='u0',origin='translate'))
        assert result.status=='conflict' and any(issue.code=='JOB_DATASET_INVALID' for issue in result.issues)
        assert store.translation('u0')==before and store.metadata()['content_revision']==content
    finally:store.close()


def test_model_writer_reads_epoch_after_acquiring_sql_write_lock(tmp_path):
    store,units,_=create(tmp_path);writer=ProjectStore(store.root);entered=threading.Event()
    job=model_job(store)
    proposal=TranslationProposal('u0','模型新稿',units[0].source_hash,0,
        job_id=job['job_id'],request_item_id='u0',origin='translate')
    def trace(sql):
        if sql.strip().upper()=='BEGIN IMMEDIATE':entered.set()
    store._connection.set_trace_callback(trace)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with writer._write() as connection:
                future=pool.submit(store.commit,proposal)
                assert entered.wait(3),'model writer never attempted to acquire SQL lock'
                connection.execute('UPDATE metadata SET value=? WHERE key=?',
                    (json.dumps(writer.metadata()['dataset_revision']+1),'dataset_revision'))
            result=future.result(timeout=5)
        assert result.status=='conflict' and any(issue.code=='DATASET_REVISION_CONFLICT' for issue in result.issues)
        assert store.translation('u0') is None
    finally:store.close();writer.close()


def test_existing_delivery_replay_stays_idempotent_after_new_dataset(tmp_path):
    store,units,_=create(tmp_path)
    try:
        job=model_job(store)
        proposal=TranslationProposal('u0','有效译文',units[0].source_hash,0,
            job_id=job['job_id'],request_item_id='u0',origin='translate')
        assert store.commit(proposal).status=='accepted'
        store.replace_units([replace(units[0],scene_id='new-context'),*units[1:]])
        before=store.translation('u0');content=store.metadata()['content_revision']
        assert store.commit(proposal).status=='duplicate'
        assert store.translation('u0')==before and store.metadata()['content_revision']==content
    finally:store.close()


def test_known_model_job_cannot_claim_another_project_identity(tmp_path):
    store,units,_=create(tmp_path)
    try:
        job=model_job(store,project_id='foreign')
        result=store.commit(TranslationProposal('u0','模型新稿',units[0].source_hash,0,
            job_id=job['job_id'],request_item_id='u0',origin='translate'))
        assert result.status=='conflict' and any(issue.code=='PROJECT_IDENTITY_CONFLICT' for issue in result.issues)
        assert store.translation('u0') is None
    finally:store.close()


@pytest.mark.parametrize('change,code',[
    ({'unit_ids':[]},'JOB_REQUEST_ITEMS_INVALID'),
    ({'unit_ids':['u0','u0']},'JOB_REQUEST_ITEMS_INVALID'),
    ({'unit_ids':['u1']},'REQUEST_ITEM_MISMATCH'),
    ({'request_id':'wrong'},'REQUEST_ITEM_MISMATCH'),
    ({'origin':'polish'},'JOB_OPERATION_CONFLICT'),
    ({'run_state':'RUNNING'},'JOB_STATE_CONFLICT'),
])
def test_model_writer_rejects_mismatched_request_membership_role_and_stage(tmp_path,change,code):
    store,units,_=create(tmp_path)
    try:
        payload={key:value for key,value in change.items() if key=='unit_ids'}
        if change.get('run_state'):
            job=store.create_job('TRANSLATE',{'unit_ids':['u0'],'dataset_revision':store.metadata()['dataset_revision']})
            store.update_job(job['job_id'],run_state=change['run_state'])
        else:job=model_job(store,**payload)
        result=store.commit(TranslationProposal('u0','模型新稿',units[0].source_hash,0,
            job_id=job['job_id'],request_item_id=change.get('request_id','u0'),origin=change.get('origin','translate')))
        assert result.status=='conflict' and any(issue.code==code for issue in result.issues)
        assert store.translation('u0') is None
    finally:store.close()
