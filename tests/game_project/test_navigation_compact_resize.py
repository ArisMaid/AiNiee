"""Expanded navigation must collapse before its layout minimum blocks resizing."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtWidgets import QApplication
from PyQt5.QtTest import QTest

_APP=QApplication.instance() or QApplication([])


def test_expanded_navigation_can_converge_to_1024_without_a_manual_toggle(tmp_path,monkeypatch):
    for key,folder in [('AINIEE_USER_DATA_DIR','user'),('AINIEE_CACHE_DIR','cache'),
            ('AINIEE_PROJECT_CACHE_DIR','projects'),('AINIEE_LOG_DIR','logs'),('TIKTOKEN_CACHE_DIR','tiktoken')]:
        monkeypatch.setenv(key,str(tmp_path/folder))
    monkeypatch.setenv('AINIEE_OFFLINE','1');monkeypatch.setenv('AINIEE_PORTABLE','1')
    from ModuleFolders.Service.Cache.CacheManager import CacheManager
    from ModuleFolders.Domain.FileReader.FileReader import FileReader
    from UserInterface.AppFluentWindow import AppFluentWindow
    app=QApplication.instance() or QApplication([])
    window=AppFluentWindow('Synthetic navigation resize acceptance',CacheManager(),FileReader())
    try:
        window.resize(1600,720);window.show();QTest.qWait(650)
        window.navigationInterface.expand(useAni=False);app.processEvents()
        expanded_min=window.minimumSizeHint().width()
        assert window.navigationInterface.panel.minimumExpandWidth>expanded_min
        # Real drags produce successive resize requests. Give the asynchronous
        # sidebar transition time to finish, then reapply the intended width.
        window.resize(1024,720);QTest.qWait(300)
        window.resize(1024,720);QTest.qWait(200)
        assert window.width()==1024 and window.height()==720
        assert window.navigationInterface.panel.isCollapsed()
    finally:
        window.systemThemeListener.requestInterruption();window.systemThemeListener.quit()
        assert window.systemThemeListener.wait(1200)
        window.hide();window.deleteLater();app.processEvents()
