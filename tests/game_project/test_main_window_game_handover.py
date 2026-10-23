import os,threading,time
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtWidgets import QApplication,QWidget
from PyQt5.QtCore import QTimer
from ModuleFolders.Base.Base import Base
from ModuleFolders.Service.Cache.CacheManager import CacheManager
from ModuleFolders.Service.Cache.CacheProject import CacheProject
from UserInterface.AppFluentWindow import AppFluentWindow
from UserInterface.GameProject.GameProjectPage import GameProjectPage


class Edit(QWidget):
    def __init__(self):
        super().__init__();self.visits=[]
        self.translation_page=SimpleNamespace(language_settings_card=Mock())
    def on_folder_selected(self,*args):self.visits.append((args,threading.get_ident()))
    def on_back_button_clicked(self):self.visits.append(('back',threading.get_ident()))


class Window(QWidget):
    for name in ('open_game_translation','_game_translation_ready','_game_translation_error',
        '_game_translation_cancelled','_cancel_game_translation','_finish_game_translation'):
        locals()[name]=getattr(AppFluentWindow,name)
    def __init__(self):
        super().__init__();self.cache_manager=CacheManager();self.edit_view_page=Edit()
        self.game_project_page=GameProjectPage(on_translate=self.open_game_translation)
        self.game_project_page._project_root='fixture';self.game_project_page._game_project_path='fixture/game-project.json'
        self.game_project_page._update_enabled()
        self.game_project_page.translationCancelRequested.connect(self._cancel_game_translation)
        self._game_translation_loader=None;self._game_translation_edit_enabled=True;self._game_translation_cancel_pending=False
        self.save_config=Mock(side_effect=lambda config:dict(config));self.switchTo=Mock()


class Service:
    def __init__(self,path):self.store=self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def metadata(self):return {'extraction_complete':True}


def settle(app,window):
    until=time.monotonic()+5
    while window._game_translation_loader is not None and time.monotonic()<until:
        app.processEvents();time.sleep(.005)
    assert window._game_translation_loader is None
    app.processEvents()


@pytest.mark.parametrize('outcome',['success','cancel','failure','task_started','config_failure'])
def test_background_handover_preserves_cache_and_ui_on_rejection(outcome):
    app=QApplication.instance() or QApplication([]);window=Window();page=window.game_project_page
    old=CacheProject(project_name='old');window.cache_manager.project=old
    new=CacheProject(project_name='new',project_type='RpgGame',extra={'game_project_root':'fixture'})
    entered=threading.Event();release=threading.Event();threads=[];ticks=[]
    def prepare(store,*,check=None):
        threads.append(threading.get_ident());entered.set();assert release.wait(3);check()
        if outcome=='failure':raise ValueError('fixture preparation error')
        return new
    with patch.object(Base,'work_status',Base.STATUS.IDLE),patch(
            'ModuleFolders.Service.GameProject.GameProjectService.GameProjectService',Service),patch(
            'ModuleFolders.Service.GameProject.CacheBridge.build_projection',side_effect=prepare),patch(
            'ModuleFolders.Service.GameProject.CacheBridge.refresh_projection',side_effect=AssertionError('duplicate projection')):
        try:
            page.translate_button.click();assert entered.wait(3)
            assert page.is_busy() and not window.edit_view_page.isEnabled() and page.cancel_button.isEnabled()
            assert not page.translate_button.isEnabled() and not page.open_button.isEnabled()
            QTimer.singleShot(0,lambda:ticks.append(True));app.processEvents();assert ticks==[True]
            window.open_game_translation('second');assert len(threads)==1
            page.error_label.clear()
            if outcome=='cancel':page.cancel_button.click()
            if outcome=='task_started':Base.work_status='fixture-running'
            if outcome=='config_failure':window.save_config.side_effect=OSError('fixture config write failure')
        finally:release.set();settle(app,window)
    assert window.edit_view_page.isEnabled() and not page.is_busy()
    assert page.translate_button.isEnabled() and not page.cancel_button.isEnabled()
    assert len(threads)==1 and threads[0]!=threading.get_ident()
    if outcome=='success':
        assert window.cache_manager.project is new
        assert window.edit_view_page.visits==[(('new','new'),threading.get_ident())]
        window.switchTo.assert_called_once_with(window.edit_view_page)
        window.save_config.assert_called_once()
        window.edit_view_page.translation_page.language_settings_card.apply_config.assert_called_once_with({
            'translation_project':'RpgGame','label_input_path':'fixture/game-project.json',
            'source_language':'japanese','target_language':'chinese_simplified'})
    else:
        assert window.cache_manager.project is old
        window.switchTo.assert_not_called()
        if outcome!='config_failure':window.save_config.assert_not_called()
        if outcome=='cancel':assert '取消' in page.status_label.text() and not page.error_label.text()
        else:assert page.error_label.text()
    page.deleteLater();window.edit_view_page.deleteLater();window.deleteLater();app.processEvents()


def test_handover_rejects_existing_model_task_before_starting_thread():
    app=QApplication.instance() or QApplication([]);window=Window()
    with patch.object(Base,'work_status','fixture-running'):
        window.open_game_translation('fixture')
    assert window._game_translation_loader is None
    assert '停止当前翻译任务' in window.game_project_page.error_label.text()
    window.deleteLater();app.processEvents()


def test_cancel_pending_after_thread_return_refuses_queued_success():
    app=QApplication.instance() or QApplication([]);window=Window()
    old=CacheProject(project_name='old');window.cache_manager.project=old
    worker=Mock();worker.isInterruptionRequested.return_value=False
    window._game_translation_loader=worker
    window._cancel_game_translation()
    with patch.object(Base,'work_status',Base.STATUS.IDLE):
        window._game_translation_ready(worker,'fixture',CacheProject(project_type='RpgGame',extra={'game_project_root':'fixture'}))
    assert window.cache_manager.project is old
    window.save_config.assert_not_called();window.switchTo.assert_not_called()
    assert '取消' in window.game_project_page.status_label.text()
    window._game_translation_loader=None;window.deleteLater();app.processEvents()


@pytest.mark.parametrize('stops',[True,False])
def test_confirmed_close_joins_theme_listener_and_refuses_destruction_if_still_running(stops):
    listener=Mock();listener.wait.return_value=stops;event=Mock();page=Mock();page.is_busy.return_value=False
    fake=SimpleNamespace(game_project_page=page,systemThemeListener=listener,tra=lambda text:text,
        emit=Mock(),info=Mock())
    dialog=Mock();dialog.exec.return_value=True
    with patch('UserInterface.AppFluentWindow.MessageBox',return_value=dialog):AppFluentWindow.closeEvent(fake,event)
    listener.requestInterruption.assert_called_once();listener.quit.assert_called_once();listener.wait.assert_called_once_with(1200)
    listener.terminate.assert_not_called()
    if stops:event.accept.assert_called_once();fake.emit.assert_called_once()
    else:event.ignore.assert_called_once();fake.emit.assert_not_called()
