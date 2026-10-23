import time
import importlib
import threading
import test_gui_workflow_acceptance as gui
from test_migration_review import projects
from test_migration_recovery import migration
from UserInterface.GameProject.MigrationDialog import MigrationDialog


def wait(dialog):
    deadline=time.monotonic()+10
    while dialog.is_busy() and time.monotonic()<deadline:
        gui._APP.processEvents();time.sleep(.01)
    gui._APP.processEvents()
    assert not dialog.is_busy(),dialog.status_label.text()


def test_review_confirmation_filter_details_and_application_through_widgets(projects):
    old,new,uid=projects
    dialog=MigrationDialog(new.store.root);dialog.show();dialog.old_edit.setText(str(old.store.root))
    dialog.plan_button.click();wait(dialog)
    assert dialog.envelope and not dialog.envelope['plan']['identity']['verified']
    assert not dialog.apply_button.isEnabled()
    dialog.confirm_box.setChecked(True);dialog.plan_button.click();wait(dialog)
    assert dialog.envelope['plan']['identity']['verified']
    assert dialog.apply_button.isEnabled()
    dialog.filter_box.setCurrentIndex(dialog.filter_box.findData('reused'))
    assert dialog.model.rowCount()==1
    dialog.table.selectRow(0);gui._APP.processEvents()
    assert '保存' in dialog.detail.toPlainText() and '存档' in dialog.detail.toPlainText()
    assert '/terms/save' in dialog.detail.toPlainText()
    dialog.apply_button.click();wait(dialog)
    assert new.store.translation(uid)['text']=='存档'
    assert '已复用 1 条' in dialog.status_label.text() and not dialog.apply_button.isEnabled()
    assert dialog.changed
    dialog.close();dialog.deleteLater();gui._APP.processEvents()


def test_known_mismatches_are_never_overridden_by_confirmation_checkbox(projects):
    old,new,uid=projects
    old.store.update_metadata({'game_id':1});new.store.update_metadata({'game_id':2})
    dialog=MigrationDialog(new.store.root);dialog.old_edit.setText(str(old.store.root));dialog.confirm_box.setChecked(True)
    dialog.plan_button.click();wait(dialog)
    assert dialog.envelope is None and not dialog.apply_button.isEnabled()
    assert 'MIGRATION_PROJECT_MISMATCH' in dialog.status_label.text()
    assert new.store.translation(uid) is None
    assert not new.store.metadata().get('migration_lineage')
    dialog.close();dialog.deleteLater();gui._APP.processEvents()


def test_offscreen_ui_font_preserves_lowercase_and_uppercase_identity():
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_fonts
    from PyQt5.QtGui import QImage,QPainter,QColor,QFontInfo
    chosen=configure_qt_fonts(gui._APP)
    assert chosen and QFontInfo(gui._APP.font()).family()
    def pixels(text):
        image=QImage(160,40,QImage.Format_RGB32);image.fill(QColor('white'))
        painter=QPainter(image);painter.setPen(QColor('black'));painter.setFont(gui._APP.font())
        painter.drawText(2,30,text);painter.end()
        pointer=image.bits();pointer.setsize(image.byteCount());return bytes(pointer)
    assert pixels('abc-123')!=pixels('ABC-123')


def test_actual_buttons_pause_continue_cancel_and_restore_registered_migration(migration,monkeypatch):
    old,new,plan=migration
    module=importlib.import_module('UserInterface.GameProject.MigrationDialog')
    original=module.apply_review;first=threading.Event();release_first=threading.Event()
    second=threading.Event();release_second=threading.Event()
    def controlled(*args,progress=None,**kwargs):
        def progress_at_boundary(done,total,detail):
            if progress:progress(done,total,detail)
            if done==1:first.set();assert release_first.wait(10)
            if done==2:second.set();assert release_second.wait(10)
        return original(*args,progress=progress_at_boundary,**kwargs)
    monkeypatch.setattr(module,'apply_review',controlled)
    dialog=MigrationDialog(new.store.root);dialog.show();dialog.old_edit.setText(str(old.store.root))
    dialog._done({'operation':'plan','result':plan});dialog._update_enabled();dialog.apply_button.click()
    def until(predicate):
        deadline=time.monotonic()+10
        while not predicate() and time.monotonic()<deadline:gui._APP.processEvents();time.sleep(.01)
        gui._APP.processEvents();assert predicate(),dialog.status_label.text()
    try:
        until(lambda:first.is_set() and dialog.pause_button.isEnabled())
        dialog.pause_button.click();release_first.set()
        until(lambda:dialog.continue_button.isEnabled())
        assert len([p for p in new.store.proposals() if p['origin']=='migration'])==1
        dialog.close();assert dialog.isVisible() and dialog.is_busy()
        dialog.continue_button.click()
        until(lambda:second.is_set() and dialog.cancel_button.isEnabled())
        dialog.cancel_button.click();release_second.set();wait(dialog)
        assert dialog.changed and not dialog.apply_button.isEnabled()
        assert len([p for p in new.store.proposals() if p['origin']=='migration'])==2
        monkeypatch.setattr(module.QInputDialog,'getItem',lambda *a,**k:(a[3][0],True))
        dialog.recover_button.click();wait(dialog)
        assert '已复用 3 条' in dialog.status_label.text()
        assert len([p for p in new.store.proposals() if p['origin']=='migration'])==3
        jobs=[j for j in new.store.jobs() if j['operation']=='MIGRATE']
        assert {j['run_state'] for j in jobs}=={'CANCELLED','COMPLETED'}
        assert next(j for j in jobs if j['run_state']=='COMPLETED')['result']['reused_units']==2
    finally:
        release_first.set();release_second.set()
        if dialog.is_busy():dialog._control('cancel');wait(dialog)
        dialog.close();dialog.deleteLater();gui._APP.processEvents()
