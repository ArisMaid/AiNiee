"""Protected small-window acceptance; content must remain reachable by scrolling."""
import os
from unittest.mock import patch
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtCore import QPoint,QRect,Qt
from PyQt5.QtWidgets import QApplication,QWidget,QVBoxLayout,QStackedWidget,QScrollArea
from PyQt5.QtTest import QTest,QSignalSpy
from ModuleFolders.Config.Config import ConfigMixin

_APP=QApplication.instance() or QApplication([])


def contained(control,ancestor):
    return ancestor.rect().contains(QRect(control.mapTo(ancestor,QPoint(0,0)),control.size()))


@pytest.fixture
def pages():
    from UserInterface.GameProject.GameProjectPage import GameProjectPage
    from UserInterface.Settings.AdvancedSettingsPage import AdvancedSettingsPage
    app=QApplication.instance() or QApplication([])
    with patch.object(ConfigMixin,'load_config',return_value={}),patch.object(ConfigMixin,'save_config',side_effect=lambda value:value):
        window=QWidget();layout=QVBoxLayout(window);layout.setContentsMargins(0,0,0,0)
        stack=QStackedWidget(window);layout.addWidget(stack)
        game=GameProjectPage();advanced=AdvancedSettingsPage('advanced',window)
        stack.addWidget(game);stack.addWidget(advanced)
        try:yield app,window,stack,game,advanced
        finally:window.hide();window.deleteLater();app.processEvents()


@pytest.mark.parametrize('width,height',[(1280,650),(1024,650)])
def test_hidden_page_minimums_do_not_expand_window_beyond_requested_size(pages,width,height):
    app,window,stack,game,advanced=pages
    for page in (game,advanced):
        stack.setCurrentWidget(page);window.resize(width,height);window.show();QTest.qWait(40)
        assert window.width()==width and window.height()==height
        assert contained(stack,window) and contained(page,stack)


def test_game_top_action_and_bottom_status_are_reachable_without_replacing_controls(pages):
    app,window,stack,game,advanced=pages
    stack.setCurrentWidget(game);window.resize(1024,650);window.show();QTest.qWait(40)
    assert window.height()==650
    scrolls=game.findChildren(QScrollArea);assert len(scrolls)==1
    scroll=scrolls[0];assert scroll.verticalScrollBar().maximum()>0
    button=game.source_button;spy=QSignalSpy(button.clicked)
    scroll.ensureWidgetVisible(button);QTest.qWait(25)
    assert contained(button,scroll.viewport())
    with patch('UserInterface.GameProject.GameProjectPage.QFileDialog.getExistingDirectory',return_value=''):
        QTest.mouseClick(button,Qt.LeftButton)
    assert len(spy)==1 and game.source_button is button
    scroll.ensureWidgetVisible(game.status_label);QTest.qWait(25)
    assert contained(game.status_label,scroll.viewport())
    assert contained(scroll.viewport(),window)
    window.resize(1280,1100);QTest.qWait(40)
    assert scroll.verticalScrollBar().maximum()==0


def test_advanced_tabs_keep_their_pages_and_bottom_content_reachable(pages):
    app,window,stack,game,advanced=pages
    stack.setCurrentWidget(advanced);window.resize(1024,650);window.show();QTest.qWait(40)
    assert window.height()==650
    scrolls=advanced.findChildren(QScrollArea);assert len(scrolls)==1
    scroll=scrolls[0]
    original=dict(advanced.route_to_widget)
    for route,widget in original.items():
        advanced.switch_tab(route);QTest.qWait(25)
        assert advanced.stacked_widget.currentWidget() is widget
        scroll.ensureWidgetVisible(advanced.tab_bar);QTest.qWait(20)
        assert contained(advanced.tab_bar,scroll.viewport())
        point=widget.mapTo(scroll.widget(),QPoint(widget.width()//2,max(0,widget.height()-2)))
        scroll.ensureVisible(point.x(),point.y(),2,2);QTest.qWait(20)
        assert scroll.viewport().rect().contains(widget.mapTo(scroll.viewport(),QPoint(widget.width()//2,max(0,widget.height()-2))))
    assert advanced.route_to_widget==original


def test_long_build_state_wraps_without_shifting_bottom_status_horizontally(pages):
    app,window,stack,game,advanced=pages
    stack.setCurrentWidget(game)
    game.last_build_label.setText('测试构建 · '+'b'*32+' · 运行期校验：'+('未执行（本工具不启动游戏）'*5))
    game.status_label.setText('构建信息仍须完整可读')
    window.resize(1024,650);window.show();QTest.qWait(50)
    scroll=game.content_scroll
    scroll.ensureWidgetVisible(game.status_label);QTest.qWait(25)
    assert scroll.horizontalScrollBar().maximum()==0
    assert contained(game.status_label,scroll.viewport())
    assert 'b'*32 in game.last_build_label.text() and game.last_build_label.text().count('未执行')==5
