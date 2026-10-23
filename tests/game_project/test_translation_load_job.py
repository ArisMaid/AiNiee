import os,threading,time
from types import SimpleNamespace
from unittest.mock import patch
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtWidgets import QApplication
from ModuleFolders.Service.Cache.CacheProject import CacheProject


def wait(app,job):
    deadline=time.monotonic()+5
    while job.isRunning() and time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
    assert job.wait(100)
    app.processEvents()


class Service:
    complete=True
    closed=[]
    def __init__(self,path):self.path=path;self.store=self
    def __enter__(self):return self
    def __exit__(self,*args):self.closed.append(threading.get_ident())
    def metadata(self):return {'extraction_complete':self.complete}


def test_projection_is_prepared_once_off_main_thread_and_service_is_closed():
    from UserInterface.GameProject.GameTranslationLoader import GameTranslationLoadJob
    app=QApplication.instance() or QApplication([])
    main=threading.get_ident();calls=[];results=[];errors=[]
    expected=CacheProject(project_type='RpgGame',extra={'game_project_root':'fixture'})
    def build(store,*,check=None):
        calls.append(threading.get_ident());check();return expected
    Service.closed=[]
    with patch('ModuleFolders.Service.GameProject.GameProjectService.GameProjectService',Service),patch(
            'ModuleFolders.Service.GameProject.CacheBridge.build_projection',side_effect=build):
        job=GameTranslationLoadJob('fixture');job.succeeded.connect(results.append);job.failed.connect(errors.append)
        job.start();wait(app,job)
    assert results==[expected] and not errors and len(calls)==1 and calls[0]!=main
    assert Service.closed==calls


def test_incomplete_project_does_not_prepare_a_projection():
    from UserInterface.GameProject.GameTranslationLoader import GameTranslationLoadJob
    app=QApplication.instance() or QApplication([]);errors=[];results=[]
    with patch.object(Service,'complete',False),patch(
            'ModuleFolders.Service.GameProject.GameProjectService.GameProjectService',Service),patch(
            'ModuleFolders.Service.GameProject.CacheBridge.build_projection') as build:
        job=GameTranslationLoadJob('fixture');job.failed.connect(errors.append);job.succeeded.connect(results.append)
        job.start();wait(app,job)
    assert not results and len(errors)==1 and 'GAME_EXTRACTION_REQUIRED' in errors[0]
    build.assert_not_called()


def test_interruption_is_cooperative_and_never_emits_success_or_failure():
    from UserInterface.GameProject.GameTranslationLoader import GameTranslationLoadJob
    app=QApplication.instance() or QApplication([]);entered=threading.Event();release=threading.Event()
    cancelled=[];results=[];errors=[]
    def build(store,*,check=None):
        entered.set()
        assert release.wait(3)
        check();raise AssertionError('cancel must stop preparation')
    with patch('ModuleFolders.Service.GameProject.GameProjectService.GameProjectService',Service),patch(
            'ModuleFolders.Service.GameProject.CacheBridge.build_projection',side_effect=build):
        job=GameTranslationLoadJob('fixture');job.succeeded.connect(results.append);job.failed.connect(errors.append)
        job.cancelled.connect(lambda:cancelled.append(True));job.start()
        try:
            assert entered.wait(3);job.requestInterruption()
        finally:release.set();wait(app,job)
    assert cancelled==[True] and not results and not errors


def test_projection_honors_check_before_loading_and_between_units():
    from ModuleFolders.Service.GameProject.CacheBridge import build_projection
    class Stop(Exception):pass
    def stop():raise Stop()
    store=SimpleNamespace(units=lambda:pytest.fail('cancelled before SQL read'))
    with pytest.raises(Stop):build_projection(store,check=stop)

