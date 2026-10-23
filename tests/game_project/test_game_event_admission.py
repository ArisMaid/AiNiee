"""Real producer, start consumer and done consumer with controlled scheduling."""
from dataclasses import replace
from types import MethodType,SimpleNamespace
from unittest.mock import Mock,patch
import importlib
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
from test_game_task_reset import seed,authority


def page_for(host,mode=TaskType.TRANSLATION):
    from UserInterface.EditView.Translation.BottomCommandBar import BottomCommandBar
    page=SimpleNamespace(cache_manager=host,current_mode=mode,has_resumable_task=False,
        ACTION_STOP=BottomCommandBar.ACTION_STOP,
        start_btn=Mock(),reset_btn=Mock(),ui_update_timer=Mock(),update_task_action_button=Mock(),
        _update_reset_button_state=Mock(),warning_toast=Mock(),tra=lambda value:value,
        _has_valid_api_binding=lambda:True,_has_sufficient_translated_lines_for_polish=lambda:True,emit=Mock())
    page.ui_update_timer.isActive.return_value=False
    for name in ('_reserve_game_start','_publish_start','task_stop_done','command_play','command_continue','_emit_timer_update'):
        setattr(page,name,MethodType(getattr(BottomCommandBar,name),page))
    return page


def executor_for(host):
    module=importlib.import_module('ModuleFolders.Service.TaskExecutor.TaskExecutor')
    executor=object.__new__(module.TaskExecutor);executor.cache_manager=host
    for name in ('emit','print','warning','error','info','_cancel_active_executor',
                 'translation_start_target','polish_start_target'):setattr(executor,name,Mock())
    return module,executor


def immediate_thread(*,target,args=(),**_):
    return SimpleNamespace(start=lambda:target(*args))


@pytest.mark.parametrize('continuing',[False,True])
@pytest.mark.parametrize('mode',[TaskType.TRANSLATION,TaskType.POLISH])
def test_valid_ui_start_claims_before_queue_and_releases_only_its_completion(tmp_path,monkeypatch,continuing,mode):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,_,host=seed(tmp_path);page=page_for(host,mode);module,executor=executor_for(host)
    try:
        before=authority(store)
        (page.command_continue if continuing else page.command_play)()
        event,data=page.emit.call_args.args
        assert event==Base.EVENT.TASK_START and data['continue_status'] is continuing
        assert Base.work_status==Base.STATUS.TASKING and coordinator_for(host).active
        assert store.jobs()==[] and data['dataset_revision']==store.metadata()['dataset_revision']
        with patch.object(module.threading,'Thread',side_effect=immediate_thread):executor.task_start(event,data)
        target=executor.translation_start_target if mode==TaskType.TRANSLATION else executor.polish_start_target
        target.assert_called_once_with(continuing,task_scope=coordinator_for(host).current)
        done_event,done=executor.emit.call_args.args
        assert done_event==Base.EVENT.TASK_STOP_DONE and done['game_execution_id']==data['game_execution_id']
        assert Base.work_status==Base.STATUS.TASKSTOPPED
        page.task_stop_done(done_event,done)
        assert Base.work_status==Base.STATUS.IDLE and authority(store)==before
        page.start_btn.setEnabled.assert_any_call(True)
        page.command_play()  # same game, new run: late previous Done is ignored
        calls=page.start_btn.setEnabled.call_count
        page.task_stop_done(done_event,done)
        assert Base.work_status==Base.STATUS.TASKING and page.start_btn.setEnabled.call_count==calls
    finally:store.close()


def test_canonical_dataset_change_releases_own_start_before_thread_or_provider(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,units,host=seed(tmp_path);page=page_for(host);module,executor=executor_for(host)
    try:
        page.command_play();event,data=page.emit.call_args.args
        store.replace_units([replace(units[0],source_text='新的来源',source_hash=''),*units[1:]])
        before=authority(store)
        with patch.object(module.threading,'Thread') as thread:executor.task_start(event,data)
        thread.assert_not_called();executor.translation_start_target.assert_not_called()
        done_event,done=executor.emit.call_args.args
        assert 'DATASET_REVISION_CONFLICT' in done['error']
        page.task_stop_done(done_event,done)
        assert Base.work_status==Base.STATUS.IDLE and authority(store)==before
        page.warning_toast.assert_called_once()
    finally:store.close()


def test_thread_start_failure_and_emit_failure_do_not_leave_reserved_busy_state(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,_,host=seed(tmp_path);page=page_for(host);module,executor=executor_for(host)
    try:
        page.command_play();event,data=page.emit.call_args.args
        with patch.object(module.threading,'Thread') as thread:
            thread.return_value.start.side_effect=RuntimeError('thread launch fault')
            with pytest.raises(RuntimeError,match='launch fault'):executor.task_start(event,data)
        page.task_stop_done(*executor.emit.call_args.args)
        assert Base.work_status==Base.STATUS.IDLE and not coordinator_for(host).active
        page.emit.side_effect=RuntimeError('queued emit fault')
        page.command_play()
        assert Base.work_status==Base.STATUS.IDLE and not coordinator_for(host).active
        assert page.start_btn.setEnabled.call_args.args==(True,)
    finally:store.close()


def test_game_continue_does_not_replace_projection_and_does_not_duplicate_savers(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    module=importlib.import_module('ModuleFolders.Service.Cache.CacheManager')
    store,_,host=seed(tmp_path);page=page_for(host);host.load_from_project_id=Mock()
    try:
        page.command_continue();event,data=page.emit.call_args.args
        project=host.project;before=authority(store)
        with patch.object(module.threading,'Thread') as thread:
            thread.return_value.is_alive.return_value=True
            host.start_interval_saving(event,data);host.start_interval_saving(event,data)
        thread.assert_called_once();host.save_to_file.assert_not_called();host.load_from_project_id.assert_not_called()
        assert host.project is project and authority(store)==before
    finally:store.close()


def test_old_stop_does_not_cancel_current_requests_or_spawn_a_watcher(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,_,host=seed(tmp_path);page=page_for(host);module,executor=executor_for(host)
    try:
        page.command_play();_,data=page.emit.call_args.args
        coordinator=coordinator_for(host);scope=coordinator.accept(host.project,data)
        with patch.object(module,'LLMClientFactory') as factory,patch.object(module.threading,'Thread') as thread:
            executor.task_stop(Base.EVENT.TASK_STOP,{**data,'game_execution_id':'old-run'})
            assert Base.work_status==Base.STATUS.TASKING
            executor._cancel_active_executor.assert_not_called();factory.assert_not_called()
            executor.task_stop(Base.EVENT.TASK_STOP,data)
            executor._cancel_active_executor.assert_called_once();factory.return_value.close_all_clients.assert_called_once()
            thread.assert_not_called()
        assert Base.work_status==Base.STATUS.STOPING and coordinator.stop_requested(scope)
    finally:store.close()


def test_terminal_owner_can_release_damaged_view_but_cannot_authorize_another_start(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,_,host=seed(tmp_path);page=page_for(host)
    try:
        page.command_play();_,data=page.emit.call_args.args
        coordinator=coordinator_for(host);scope=coordinator.accept(host.project,data)
        host.project.set_extra('game_dataset_revision',scope.dataset_revision+1)
        coordinator.finish(scope);Base.work_status=Base.STATUS.TASKSTOPPED
        page.task_stop_done(Base.EVENT.TASK_STOP_DONE,scope.payload())
        assert Base.work_status==Base.STATUS.IDLE and host.project.get_extra('game_projection_refresh_required')
        page.emit.reset_mock();page.command_play();page.emit.assert_not_called()
        assert Base.work_status==Base.STATUS.IDLE and not coordinator.active
    finally:store.close()


@pytest.mark.parametrize('mode',[TaskType.TRANSLATION,TaskType.POLISH])
def test_game_continue_checks_platform_before_claiming_or_publishing(tmp_path,monkeypatch,mode):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,_,host=seed(tmp_path);page=page_for(host,mode)
    page._has_valid_api_binding=lambda:False
    try:
        page.command_continue();page.emit.assert_not_called()
        assert Base.work_status==Base.STATUS.IDLE and coordinator_for(host).current is None
    finally:store.close()


@pytest.mark.parametrize('mode',[None,True,'1000'])
def test_bad_ui_mode_does_not_claim_a_task(tmp_path,monkeypatch,mode):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,_,host=seed(tmp_path);page=page_for(host,mode)
    try:
        assert page._reserve_game_start() is None
        assert Base.work_status==Base.STATUS.IDLE and coordinator_for(host).current is None
        page.warning_toast.assert_called_once()
    finally:store.close()
