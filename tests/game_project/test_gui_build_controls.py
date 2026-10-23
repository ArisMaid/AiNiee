"""Protected compact history lookup and identity-preserving action tabs."""
import os
from unittest.mock import patch
import pytest
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore


@pytest.fixture
def store(tmp_path):
    with ProjectStore.create(tmp_path/'project',{'project_id':'build-controls','engine':'rpgmaker-mz',
            'source_root':str(tmp_path/'source')}) as current:yield current


def test_empty_build_history_returns_none_without_writing(store):
    before=store.metadata()
    assert store.latest_build_summary() is None
    assert store.metadata()==before


def test_latest_build_is_compact_ordered_and_preserves_optional_legacy_fields(store,tmp_path):
    from ModuleFolders.Service.GameProject import ProjectStore as module
    with patch.object(module,'_utc_now',return_value='2026-10-18T10:00:00Z'):
        store.record_build({'build_id':'a','output_path':'old','files':['x'*(2*1024*1024)]})
        store.record_build({'build_id':'b','project_id':'build-controls','input_digest':'digest',
            'output_path':str(tmp_path/'output'),'mode':'test','runtime_validation':'not_run',
            'files':['y'*(2*1024*1024)]})
    before=store.metadata()
    with (patch.object(store,'builds',side_effect=AssertionError('history decoded')),
          patch.object(module,'_build_dict',side_effect=AssertionError('full JSON decoded'))):
        assert store.latest_build_summary()=={'build_id':'b','input_digest':'digest','project_id':'build-controls',
            'output_path':str(tmp_path/'output'),'mode':'test','runtime_validation':'not_run',
            'recorded_at':'2026-10-18T10:00:00Z'}
    assert store.metadata()==before


def test_minimal_legacy_build_and_readonly_snapshot_are_supported(store,tmp_path):
    store.record_build({'build_id':'legacy'})
    expected={'build_id':'legacy','input_digest':store.builds()[0]['input_digest'],
        'project_id':None,'output_path':None,'mode':None,
        'runtime_validation':None,'recorded_at':store.builds()[0]['recorded_at']}
    assert store.latest_build_summary()==expected
    destination=tmp_path/'snapshot/project.sqlite3';store.snapshot(destination)
    with ProjectStore(destination.parent,readonly=True) as frozen:assert frozen.latest_build_summary()==expected


def test_action_tabs_keep_the_exact_controls_and_original_signal_connections():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
    configure_qt_paths()
    from PyQt5.QtWidgets import QApplication,QWidget,QPushButton,QComboBox
    from UserInterface.GameProject.ActionTabs import build_action_tabs
    app=QApplication.instance() or QApplication([]);page=QWidget();events=[]
    names=('create_button extract_button refresh_button validate_button test_build_button release_build_button '
        'export_button import_button translate_button resume_scan_button resume_extract_button '
        'resume_validation_button resume_build_button font_button backend_button compare_backend_button '
        'images_button migration_button external_tools_button tpp_export_button tpp_open_button tpp_pull_button tpp_import_button').split()
    controls={name:QPushButton(name,page) for name in names}
    for name,button in controls.items():
        setattr(page,name,button);button.clicked.connect(lambda checked=False,key=name:events.append(key))
    page.tpp_binding=QComboBox(page);controls['tpp_binding']=page.tpp_binding
    tabs=build_action_tabs(page)
    try:
        assert tabs.parent() is page and tabs.objectName()=='rpg-action-tabs'
        assert [tabs.tabText(i) for i in range(tabs.count())]==['常用操作','工具与恢复','Translator++']
        assert tabs.currentIndex()==0 and events==[]
        assert all(getattr(page,name) is widget and tabs.isAncestorOf(widget) for name,widget in controls.items())
        assert len(tabs.findChildren(QPushButton))==23
        page.create_button.click();tabs.setCurrentIndex(1);page.resume_build_button.click()
        assert events==['create_button','resume_build_button']
    finally:page.deleteLater();app.processEvents()
