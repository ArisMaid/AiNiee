"""Owner regressions: foreign Start/Done must not affect the selected game."""
from types import SimpleNamespace
from unittest.mock import Mock,patch
import importlib
from ModuleFolders.Base.Base import Base
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType

def current_projection():
    return SimpleNamespace(project_type='RpgGame',project_id='new-project',
        get_extra=lambda key: 'new-root' if key=='game_project_root' else None)

def test_foreign_completion_must_not_mark_a_new_game_task_idle(monkeypatch):
    from UserInterface.EditView.Translation.BottomCommandBar import BottomCommandBar
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    page=SimpleNamespace(cache_manager=SimpleNamespace(project=current_projection()),
        ui_update_timer=SimpleNamespace(isActive=lambda:False),start_btn=Mock(),
        update_task_action_button=Mock(),_update_reset_button_state=Mock(),emit=Mock())
    BottomCommandBar.task_stop_done(page,Base.EVENT.TASK_STOP_DONE,
        {'game_project_root':'old-root','project_id':'old-project','dataset_revision':1})
    assert Base.work_status==Base.STATUS.TASKING
    page.start_btn.setEnabled.assert_not_called()
    page.emit.assert_not_called()

def test_foreign_start_must_be_rejected_before_launching_a_new_project_thread():
    module=importlib.import_module('ModuleFolders.Service.TaskExecutor.TaskExecutor')
    executor=object.__new__(module.TaskExecutor)
    executor.cache_manager=SimpleNamespace(project=current_projection())
    executor.translation_start_target=Mock();executor.polish_start_target=Mock()
    executor.emit=Mock();executor.warning=Mock();executor.error=Mock();executor.print=Mock()
    with patch.object(module.threading,'Thread') as thread:
        executor.task_start(Base.EVENT.TASK_START,{'current_mode':TaskType.TRANSLATION,'continue_status':False,
            'game_project_root':'old-root','project_id':'old-project','dataset_revision':1})
    thread.assert_not_called()
