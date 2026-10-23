"""Protected actual ancestor-clipping and hit-test evidence for GUI acceptance."""
import json,os
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtWidgets import QApplication,QWidget,QPushButton
from PyQt5.QtGui import QRegion
from PyQt5.QtTest import QTest

_APP=QApplication.instance() or QApplication([])


@pytest.fixture
def controls():
    app=QApplication.instance() or QApplication([])
    root=QWidget();root.resize(300,180)
    page=QWidget(root);page.setGeometry(0,0,300,180)
    button=QPushButton('Synthetic control',page);button.setGeometry(50,110,180,30)
    root.show();QTest.qWait(20)
    try:yield app,root,page,button
    finally:root.hide();root.deleteLater();app.processEvents()


def describe(root,button):
    from UserInterface.Native.ControlVisibility import control_visibility
    result=control_visibility(root,button)
    json.dumps(result)
    return result


def test_visible_control_is_hit_tested_and_disabled_state_is_reported_separately(controls):
    app,root,page,button=controls
    report=describe(root,button)
    assert report['fully_visible'] and report['hit_test'] and report['enabled']
    button.setEnabled(False)
    report=describe(root,button)
    assert report['fully_visible'] and not report['enabled']


def test_visible_flag_does_not_hide_intermediate_ancestor_clipping(controls):
    app,root,page,button=controls
    page.move(0,60);app.processEvents()
    assert button.isVisible()
    report=describe(root,button)
    assert not report['fully_visible'] and report['clipped_by']
    assert not report['hit_test']


def test_hidden_parent_and_zero_size_are_not_accepted(controls):
    app,root,page,button=controls
    page.hide();app.processEvents();assert not describe(root,button)['fully_visible']
    page.show();button.resize(0,0);app.processEvents();assert not describe(root,button)['fully_visible']


def test_sibling_covering_control_is_not_accepted(controls):
    app,root,page,button=controls
    overlay=QWidget(root);overlay.setGeometry(button.geometry());overlay.show();overlay.raise_();app.processEvents()
    report=describe(root,button)
    assert not report['hit_test'] and not report['fully_visible']


def test_partially_masked_control_is_not_accepted_even_when_center_can_be_hit(controls):
    app,root,page,button=controls
    page.setMask(QRegion(80,0,220,180));app.processEvents()
    report=describe(root,button)
    assert not report['fully_visible']


def test_opaque_sibling_covering_only_an_edge_is_not_accepted(controls):
    app,root,page,button=controls
    overlay=QWidget(root);overlay.setGeometry(50,110,30,30)
    overlay.setAutoFillBackground(True);overlay.show();overlay.raise_();app.processEvents()
    report=describe(root,button)
    assert report['hit_test'] and not report['fully_visible']


def test_control_own_partial_mask_is_not_accepted(controls):
    app,root,page,button=controls
    button.setMask(QRegion(20,0,160,30));app.processEvents()
    assert not describe(root,button)['fully_visible']


def test_opaque_scroll_viewport_content_does_not_count_as_covering_its_own_button(controls):
    from PyQt5.QtWidgets import QScrollArea
    app,root,page,button=controls
    scroll=QScrollArea(root);scroll.setGeometry(0,0,300,180)
    body=QWidget();body.resize(300,180);body.setAutoFillBackground(True)
    button.setParent(body);scroll.setWidget(body);scroll.setWidgetResizable(True)
    scroll.show();scroll.raise_();button.show();app.processEvents()
    report=describe(root,button)
    assert report['hit_test'] and report['fully_visible'],report


def test_unrelated_root_is_refused(controls):
    app,root,page,button=controls
    other=QWidget()
    try:
        from UserInterface.Native.ControlVisibility import control_visibility
        with pytest.raises(ValueError):control_visibility(other,button)
    finally:other.deleteLater();app.processEvents()
