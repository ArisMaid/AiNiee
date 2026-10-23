"""Actual monitor and delayed continue consumers reject previous identities."""
from types import SimpleNamespace,MethodType
from unittest.mock import Mock
import importlib
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from test_game_task_reset import seed


@pytest.mark.parametrize('damage',['none','root','project_id','dataset','execution','missing'])
def test_monitor_filters_scope_before_changing_any_metric(tmp_path,monkeypatch,damage):
    from UserInterface.EditView.Translation.MonitoringPage import MonitoringPage
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,host=seed(tmp_path)
    try:
        coordinator=coordinator_for(host);scope=coordinator.reserve(host.project,'translate')
        coordinator.accept(host.project,scope.payload());data=scope.payload()
        if damage=='root':data['game_project_root']='foreign-root'
        elif damage=='project_id':data['project_id']='foreign-id'
        elif damage=='dataset':data['dataset_revision']+=1
        elif damage=='execution':data['game_execution_id']='previous-run'
        elif damage=='missing':data={}
        methods=('update_time','update_line','update_token','update_stability','update_task','update_status')
        page=SimpleNamespace(cache_manager=host,**{name:Mock() for name in methods})
        MonitoringPage.data_update(page,Base.EVENT.TASK_UPDATE,data)
        assert all(getattr(page,name).called==(damage=='none') for name in methods)
    finally:store.close()


def continue_page(host):
    from UserInterface.EditView.EditViewPage import EditViewPage
    page=SimpleNamespace(cache_manager=host,_continue_check_generation=0,continueCheckResult=Mock(),
        continueCardStateChanged=Mock(),resumableStateChanged=Mock(),
        translation_page=SimpleNamespace(bottom_bar=SimpleNamespace(current_mode=TaskType.TRANSLATION)))
    for name in ('_continue_project_key','_capture_continue_check','_apply_continue_check_result','task_continue_check_target'):
        setattr(page,name,MethodType(getattr(EditViewPage,name),page))
    host.list_project_histories=Mock(return_value=[{'project_name':'history','line':1,'total_line':5}])
    return page


@pytest.mark.parametrize('change',['none','project','dataset','new-run','new-check','busy'])
def test_delayed_continue_result_is_rechecked_at_the_actual_ui_consumer(tmp_path,monkeypatch,change):
    module=importlib.import_module('UserInterface.EditView.EditViewPage')
    monkeypatch.setattr(module.time,'sleep',lambda *_:None)
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,_,host=seed(tmp_path);page=continue_page(host)
    try:
        host.project.stats_data.total_line=5;host.project.stats_data.line=1
        snapshot=page._capture_continue_check();page.task_continue_check_target(snapshot)
        result=page.continueCheckResult.emit.call_args.args[0]
        if change=='project':host.project=build_projection(store)
        elif change=='dataset':host.project.set_extra('game_dataset_revision',snapshot['project_key'][2]+1)
        elif change=='new-run':
            coordinator=coordinator_for(host);scope=coordinator.reserve(host.project,'translate')
            coordinator.accept(host.project,scope.payload());coordinator.finish(scope)
        elif change=='new-check':page._capture_continue_check()
        elif change=='busy':Base.work_status=Base.STATUS.TASKING
        page._apply_continue_check_result(result)
        if change=='none':
            page.resumableStateChanged.emit.assert_called_once_with(True)
            page.continueCardStateChanged.emit.assert_called_once_with(True,'history')
        else:
            page.resumableStateChanged.emit.assert_not_called();page.continueCardStateChanged.emit.assert_not_called()
    finally:store.close()


def test_game_continue_uses_current_stats_and_pending_role_instead_of_foreign_history(tmp_path,monkeypatch):
    module=importlib.import_module('UserInterface.EditView.EditViewPage')
    monkeypatch.setattr(module.time,'sleep',lambda *_:None)
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    from test_game_batch_preparation import create
    from test_game_task_reset import manager
    store,_,_=create(tmp_path);host=manager(build_projection(store));page=continue_page(host)
    try:
        snapshot=page._capture_continue_check();page.task_continue_check_target(snapshot)
        page._apply_continue_check_result(page.continueCheckResult.emit.call_args.args[0])
        page.resumableStateChanged.emit.assert_called_once_with(False)  # a fresh project has no resumable task
    finally:store.close()


@pytest.mark.parametrize('entry',['load_from_project','_adopt_prepared_game_projection','load_from_project_id','load_from_file'])
def test_supported_adoption_entries_reject_an_active_game_before_replacement(tmp_path,entry):
    store,_,host=seed(tmp_path);coordinator=coordinator_for(host)
    coordinator.reserve(host.project,'translate');project=host.project
    try:
        argument=build_projection(store) if entry in ('load_from_project','_adopt_prepared_game_projection') else 'unread-path'
        with pytest.raises(ValueError,match='PROJECT_SWITCH_BLOCKED'):getattr(host,entry)(argument)
        assert host.project is project
    finally:store.close()


def test_ui_completion_must_be_consumed_before_supported_adoption_or_new_admission(tmp_path):
    store,_,host=seed(tmp_path);coordinator=coordinator_for(host)
    try:
        scope=coordinator.reserve_current(host,'translate',ui_owned=True)
        coordinator.accept(host.project,scope.payload());coordinator.finish(scope)
        replacement=build_projection(store)
        with pytest.raises(ValueError,match='PROJECT_SWITCH_BLOCKED'):host.load_from_project(replacement)
        with pytest.raises(ValueError,match='COMPLETION_PENDING'):coordinator.reserve_current(host,'polish')
        assert coordinator.consume_done(host.project,scope.payload())
        host.load_from_project(replacement)
        assert host.project is not scope.project
        assert coordinator.reserve_current(host,'polish').project is host.project
    finally:store.close()
