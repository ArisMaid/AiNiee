"""A saved reset and a rejected transaction are distinct user-visible outcomes."""
from unittest.mock import Mock,patch
from types import SimpleNamespace
import importlib
import pytest
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
from ModuleFolders.Service.GameProject.CacheBridge import refresh_projection
from test_game_task_reset import seed,by_id,authority


def test_saved_reset_refresh_failure_requires_reload_and_keeps_accepted_reset(tmp_path):
    from ModuleFolders.Service.GameProject.CacheBridge import ResetProjectionRefreshRequired
    store,_,host=seed(tmp_path);before=store.translation('u0');revision=store.metadata()['content_revision']
    try:
        with patch('ModuleFolders.Service.GameProject.CacheBridge.build_projection',side_effect=RuntimeError('projection fault')):
            with pytest.raises(ResetProjectionRefreshRequired) as caught:host.reset_project_status(TaskType.TRANSLATION)
        assert caught.value.changed_count==2
        assert store.translation('u0')['text']==before['text']
        assert store.translation('u0')['revision']==before['revision']+1
        assert store.metadata()['content_revision']==revision+1
        assert host.project.get_extra('game_projection_refresh_required') is True
        saved=authority(store)
        with pytest.raises(ValueError,match='REFRESH_REQUIRED'):host.reset_project_status(TaskType.TRANSLATION)
        with pytest.raises(ValueError,match='REFRESH_REQUIRED'):
            host.update_item_text('data/Map001.json',0,'translated_text','must not apply')
        assert authority(store)==saved
        host.project=refresh_projection(host.project)
        assert not host.project.get_extra('game_projection_refresh_required')
        assert by_id(host.project)['u0'].translation_status==0
        assert host.reset_project_status(TaskType.TRANSLATION)==0
    finally:store.close()


def test_real_reset_command_warns_saved_and_reload_instead_of_false_failure(tmp_path,monkeypatch):
    module=importlib.import_module('UserInterface.EditView.Translation.BottomCommandBar')
    store,_,host=seed(tmp_path)
    dialog=SimpleNamespace(yesButton=Mock(),cancelButton=Mock(),exec=lambda:True)
    monkeypatch.setattr(module,'MessageBox',lambda *_:dialog)
    page=SimpleNamespace(_can_reset_project=lambda **_:True,_update_reset_button_state=Mock(),
        tra=lambda value:value,window=lambda:None,cache_manager=host,info_toast=Mock(),
        error_toast=Mock(),warning_toast=Mock(),success_toast=Mock(),emit=Mock(),update_task_action_button=Mock())
    try:
        with patch('ModuleFolders.Service.GameProject.CacheBridge.build_projection',side_effect=RuntimeError('projection fault')):
            module.BottomCommandBar.command_reset_status(page,TaskType.TRANSLATION)
        page.warning_toast.assert_called_once()
        assert '已保存' in str(page.warning_toast.call_args) and '重新' in str(page.warning_toast.call_args)
        assert not page.error_toast.called and not page.success_toast.called
        assert store.translation('u0')['origin']=='reset-translate'
    finally:store.close()
