"""The parent execution binds actual persisted jobs before local provider work."""
from types import SimpleNamespace
from unittest.mock import Mock,patch
from concurrent.futures import Future
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner
from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
from test_game_event_admission import executor_for
from test_game_task_reset import seed,by_id
from test_game_batch_preparation import config,Requester
from ModuleFolders.Service.Cache.CacheProject import CacheProjectStatistics


def request_case(tmp_path):
    store,_,host=seed(tmp_path)
    coordinator=coordinator_for(host);scope=coordinator.reserve(host.project,'translate')
    coordinator.accept(host.project,scope.payload())
    module,executor=executor_for(host)
    batch=GameBatchRunner([by_id(host.project)['u3']],config(),execution_scope=scope)
    return store,host,coordinator,scope,module,executor,batch


def test_scoped_batch_requires_parent_binding_before_any_job_or_provider(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,host,_,_,_,_,batch=request_case(tmp_path);requester=Requester()
    try:
        with pytest.raises(ValueError,match='CALLBACK_REQUIRED'):batch.run(requester)
        assert store.jobs()==[] and requester.calls==[]
    finally:store.close()


def test_foreign_projection_before_binding_fails_real_job_without_provider(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,host,coordinator,scope,_,executor,batch=request_case(tmp_path);requester=Requester()
    try:
        def switch(info):
            host.project=SimpleNamespace(project_type='RpgGame',project_id='foreign')
            executor._bind_game_job(scope,info)
        with pytest.raises(ValueError,match='PROJECT_CHANGED'):
            batch.run(requester,on_job=switch,on_job_done=lambda info:executor._release_game_job(scope,info))
        assert requester.calls==[] and store.jobs()[-1]['run_state']=='FAILED'
        assert store.jobs()[-1]['payload']['game_execution_id']==scope.execution_id
        assert store.translation('u3') is None and coordinator.active_job_ids(scope)==()
    finally:store.close()


@pytest.mark.parametrize('stop_point',['before-binding','after-binding','during-response','app-shutdown'])
def test_owned_stop_cancels_the_exact_request_and_keeps_accepted_text(tmp_path,monkeypatch,stop_point):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,host,coordinator,scope,module,executor,batch=request_case(tmp_path);requester=Requester()
    try:
        before={uid:store.translation(uid) for uid in ('u0','u1','u2','u3')}
        def bind(info):
            if stop_point=='before-binding':coordinator.request_stop(host.project,scope.payload())
            executor._bind_game_job(scope,info)
            if stop_point=='after-binding':executor.task_stop(Base.EVENT.TASK_STOP,scope.payload())
            elif stop_point=='app-shutdown':executor.app_shut_down(Base.EVENT.APP_SHUT_DOWN,{})
        if stop_point=='during-response':
            real=requester.sent_request
            def reply(*args):
                executor.task_stop(Base.EVENT.TASK_STOP,scope.payload())
                return real(*args)
            requester.sent_request=reply
        with patch.object(module,'LLMClientFactory'):
            result=batch.run(requester,on_job=bind,on_job_done=lambda info:executor._release_game_job(scope,info))
        assert result['cancelled'] and not result['check_result']
        assert len(requester.calls)==int(stop_point=='during-response')
        job=store.jobs()[-1]
        assert job['run_state']=='CANCELLED' and job['payload']['game_execution_id']==scope.execution_id
        assert {uid:store.translation(uid) for uid in before}==before
        assert coordinator.active_job_ids(scope)==()
    finally:store.close()


@pytest.mark.parametrize('mismatch',['previous-run','unknown-job'])
def test_future_result_cannot_change_new_run_stats_or_save_the_wrong_projection(tmp_path,monkeypatch,mismatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,host,coordinator,scope,_,executor,_=request_case(tmp_path)
    try:
        stats=CacheProjectStatistics();new_stats=CacheProjectStatistics()
        executor.project_status_data=new_stats;host.require_save_to_file=Mock()
        if mismatch=='previous-run':
            coordinator.finish(scope)
            new=coordinator.reserve(host.project,'translate');coordinator.accept(host.project,new.payload())
        future=Future();future.set_result({'check_result':True,'row_count':5,'prompt_tokens':4,
            'completion_tokens':3,'job_id':'not-owned'})
        executor.task_done_callback(future,task_scope=scope,stats=stats)
        assert stats.line==new_stats.line==0 and stats.token==new_stats.token==0
        host.require_save_to_file.assert_not_called();executor.emit.assert_not_called()
    finally:store.close()


def test_parent_binding_checks_that_the_job_actually_exists_in_this_project(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,host,coordinator,scope,_,executor,_=request_case(tmp_path)
    try:
        with pytest.raises(ValueError,match='JOB_CONTEXT_INVALID'):
            executor._bind_game_job(scope,scope.payload(job_id='invented'))
        assert coordinator.job_ids(scope)==() and store.jobs()==[]
    finally:store.close()
