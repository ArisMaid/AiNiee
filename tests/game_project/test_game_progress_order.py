"""Actual callback ordering and monitor rejection of stale progress snapshots."""
from concurrent.futures import Future,ThreadPoolExecutor
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Service.Cache.CacheProject import CacheProjectStatistics
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner
from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
from test_game_event_admission import executor_for
from test_game_task_reset import seed,by_id
from test_game_batch_preparation import config,Requester

def test_old_same_run_progress_snapshot_cannot_roll_back_newer_display(tmp_path,monkeypatch):
    from UserInterface.EditView.Translation.MonitoringPage import MonitoringPage
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,host=seed(tmp_path);coordinator=coordinator_for(host)
    scope=coordinator.reserve(host.project,'translate');coordinator.accept(host.project,scope.payload())
    _,executor=executor_for(host);stats=CacheProjectStatistics();stats.total_line=2;executor.project_status_data=stats
    ready=threading.Event();release=threading.Event();save_calls=[];display={}
    page=SimpleNamespace(cache_manager=host,update_time=Mock(),update_token=Mock(),update_stability=Mock(),
        update_task=Mock(),update_status=Mock(),update_line=lambda event,data:display.update(line=data.get('line',display.get('line',0))))
    executor.emit=lambda event,data:MonitoringPage.data_update(page,event,data)
    def saving():
        save_calls.append(1)
        if len(save_calls)==1:
            ready.set();assert release.wait(5)
    host.require_save_to_file=saving
    try:
        results=[]
        for uid in ('u3','u4'):
            batch=GameBatchRunner([by_id(host.project)[uid]],config(),execution_scope=scope)
            results.append(batch.run(Requester(),on_job=lambda info:executor._bind_game_job(scope,info),
                on_job_done=lambda info:executor._release_game_job(scope,info)))
        futures=[]
        for result in results:
            future=Future();future.set_result(result);futures.append(future)
        with ThreadPoolExecutor(max_workers=1) as pool:
            old=pool.submit(executor.task_done_callback,futures[0],task_scope=scope,stats=stats)
            try:
                assert ready.wait(5)
                executor.task_done_callback(futures[1],task_scope=scope,stats=stats)
            finally:release.set()
            old.result(timeout=5)
        assert stats.line==2 and display['line']==2
    finally:release.set();store.close()


@pytest.mark.parametrize('revision',[None,True,-1,0,1,'2'])
def test_invalid_or_older_metrics_do_not_change_any_monitor_card(tmp_path,monkeypatch,revision):
    from UserInterface.EditView.Translation.MonitoringPage import MonitoringPage
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,host=seed(tmp_path);coordinator=coordinator_for(host)
    try:
        scope=coordinator.reserve(host.project,'translate');coordinator.accept(host.project,scope.payload())
        methods=('update_time','update_line','update_token','update_stability','update_task','update_status')
        page=SimpleNamespace(cache_manager=host,data={'line':1},_game_progress_execution=scope.execution_id,
            _game_progress_revision=1,**{name:Mock() for name in methods})
        MonitoringPage.data_update(page,Base.EVENT.TASK_UPDATE,
            {**scope.payload(),'line':0,'total_line':2,'game_progress_revision':revision})
        assert page.data=={'line':1} and page._game_progress_revision==1
        assert all(not getattr(page,name).called for name in methods)
    finally:store.close()


def test_new_execution_timer_clears_previous_metrics_before_first_snapshot(tmp_path,monkeypatch):
    from UserInterface.EditView.Translation.MonitoringPage import MonitoringPage
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,host=seed(tmp_path);coordinator=coordinator_for(host)
    try:
        old=coordinator.reserve(host.project,'translate');coordinator.accept(host.project,old.payload())
        coordinator.finish(old)
        scope=coordinator.reserve(host.project,'polish');coordinator.accept(host.project,scope.payload())
        methods=('update_time','update_line','update_token','update_stability','update_task','update_status')
        page=SimpleNamespace(cache_manager=host,data={'line':10,'token':20},_game_progress_execution=old.execution_id,
            _game_progress_revision=8,**{name:Mock() for name in methods})
        MonitoringPage.data_update(page,Base.EVENT.TASK_UPDATE,scope.payload())
        assert page.data=={} and page._game_progress_revision==-1
        MonitoringPage.data_update(page,Base.EVENT.TASK_UPDATE,
            {**scope.payload(),'line':0,'total_line':2,'game_progress_revision':0})
        assert page._game_progress_revision==0 and page.update_line.call_count==2
        MonitoringPage.data_update(page,Base.EVENT.TASK_UPDATE,old.payload())
        assert page.update_line.call_count==2
    finally:store.close()
