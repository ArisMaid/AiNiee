"""Actual Qt queued delivery rechecks identity in the receiver thread."""
import threading
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
from test_game_event_consumers import continue_page
from test_game_task_reset import seed

@pytest.mark.parametrize('change',['none','projection','execution'])
def test_real_qt_queue_checks_identity_at_delivery(tmp_path,monkeypatch,change):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
    configure_qt_paths()
    from PyQt5.QtCore import QObject,pyqtSignal,pyqtSlot,Qt,QThread
    from PyQt5.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,_,host=seed(tmp_path);page=continue_page(host)
    class Receiver(QObject):
        result=pyqtSignal(object)
        def __init__(self):
            super().__init__();self.delivered=0
            self.result.connect(self.apply,Qt.QueuedConnection)
        @pyqtSlot(object)
        def apply(self,value):
            assert QThread.currentThread() is app.thread()
            self.delivered+=1;page._apply_continue_check_result(value)
    receiver=Receiver();page.continueCheckResult=receiver.result
    try:
        snapshot=page._capture_continue_check()
        worker=threading.Thread(target=page.task_continue_check_target,args=(snapshot,))
        worker.start();worker.join(timeout=5);assert not worker.is_alive()
        assert receiver.delivered==0
        if change=='projection':host.project=build_projection(store)
        elif change=='execution':
            coordinator=coordinator_for(host);scope=coordinator.reserve(host.project,'translate')
            coordinator.accept(host.project,scope.payload());coordinator.finish(scope)
        app.processEvents()
        assert receiver.delivered==1
        assert page.resumableStateChanged.emit.called==(change=='none')
        assert page.continueCardStateChanged.emit.called==(change=='none')
    finally:store.close()
