import os,threading,time
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtWidgets import QApplication


def test_native_theme_listener_can_stop_without_terminating_a_thread():
    from UserInterface.StoppableThemeListener import StoppableThemeListener
    app=QApplication.instance() or QApplication([]);seen=threading.Event()
    def theme():seen.set();return 'Light'
    with patch('darkdetect.theme',side_effect=theme),patch('darkdetect.listener',side_effect=AssertionError('blocking listener forbidden')):
        listener=StoppableThemeListener();listener.start()
        assert seen.wait(2)
        listener.requestInterruption();listener.quit()
        assert listener.wait(1200)
        assert not listener.isRunning()
    app.processEvents()


def test_changed_valid_theme_is_forwarded_to_inherited_callback_with_required_argument():
    from UserInterface.StoppableThemeListener import StoppableThemeListener
    app=QApplication.instance() or QApplication([]);changed=[];complete=threading.Event()
    samples=iter([' Light ','Light',None,RuntimeError('detection error'),'Dark','Dark','Light'])
    def theme():
        value=next(samples,'Light')
        if isinstance(value,Exception):raise value
        return value
    def callback(value):
        changed.append(value)
        if len(changed)==3:complete.set()
    with patch('darkdetect.theme',side_effect=theme):
        listener=StoppableThemeListener();listener._POLLS_PER_SECOND=1;listener._POLL_INTERVAL_MS=5
        listener._onThemeChanged=callback
        try:listener.start();assert complete.wait(2)
        finally:listener.requestInterruption();assert listener.wait(1200)
    assert changed==['light','dark','light']
    app.processEvents()

