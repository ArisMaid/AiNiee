import json
from pathlib import Path
from unittest.mock import patch

import pytest
from test_external_tasks import project
from ModuleFolders.Service.GameProject.CommandAuditService import audit_commands, load_audit_report
from ModuleFolders.Service.GameProject.JobControl import JobCancelled, request_action


def reports(store):
    return list((store.root / 'work/command-audits').glob('*.json'))


def test_inventory_has_exact_locations_and_small_persisted_job_result(project):
    store = project.store
    before, units = store.metadata(), [unit.to_dict() for unit in store.units()]
    result = audit_commands(store)
    report = load_audit_report(store, result)
    assert result['record_count'] > 0 and report['record_count'] == len(report['records'])
    assert all(row['path'] and row['scene_id'] and row['pointer'].startswith('/') for row in report['records'])
    assert sum(result['counts'].values()) == sum(row['command_count'] for row in report['records'])
    assert result['writes_enabled'] is False and result['reference_only'] is True
    assert store.metadata() == before and [unit.to_dict() for unit in store.units()] == units
    job = store.jobs()[-1]
    assert job['operation'] == 'COMMAND_AUDIT' and job['run_state'] == 'COMPLETED'
    assert 'records' not in job['result'] and len(json.dumps(job['result'])) < 4096
    Path(result['report_path']).write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='COMMAND_AUDIT_REPORT_CHANGED'):
        load_audit_report(store, result)


def test_cancel_before_scan_does_not_publish(project):
    with pytest.raises(JobCancelled):
        audit_commands(project.store, on_job=lambda job: request_action(project.store, job['job_id'], 'cancel'))
    assert project.store.jobs()[-1]['run_state'] == 'CANCELLED'
    assert not reports(project.store)


def test_cancel_between_scanned_commands_does_not_publish(project):
    import ModuleFolders.Service.GameProject.CommandAuditService as module
    original = module.inventory_document
    ids = []
    def scan(*args, **kwargs):
        result = original(*args, **kwargs)
        request_action(project.store, ids[0], 'cancel')
        return result
    with patch.object(module, 'inventory_document', side_effect=scan), pytest.raises(JobCancelled):
        audit_commands(project.store, on_job=lambda job: ids.append(job['job_id']))
    assert not reports(project.store)


def test_changed_dataset_refuses_completed_report(project):
    import ModuleFolders.Service.GameProject.CommandAuditService as module
    original = module.inventory_document
    changed = []
    def scan(*args, **kwargs):
        result = original(*args, **kwargs)
        if not changed:
            changed.append(True)
            project.store.replace_units(project.store.units()[:-1])
        return result
    with patch.object(module, 'inventory_document', side_effect=scan), pytest.raises(ValueError, match='COMMAND_AUDIT_INPUT_CHANGED'):
        audit_commands(project.store)
    assert not reports(project.store)
    assert project.store.jobs()[-1]['run_state'] == 'FAILED'


def test_source_snapshot_corruption_is_refused(project):
    record = next(row for row in project.store.files() if row['relative_path'] == 'data/Map001.json')
    (project.store.root / record['captured_path']).write_bytes(b'[]')
    with pytest.raises(ValueError, match='COMMAND_AUDIT_SNAPSHOT_CHANGED'):
        audit_commands(project.store)
    assert not reports(project.store)


def test_locatable_view_has_no_row_cap_and_shows_exact_source(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
    configure_qt_paths()
    from PyQt5.QtWidgets import QApplication, QAbstractItemView
    from PyQt5.QtCore import Qt
    from UserInterface.GameProject.CommandAuditDialog import CommandAuditDialog
    app = QApplication.instance() or QApplication([])
    rows = [{'path': 'data/Map001.json', 'scene_id': 'Map001:event:7:page:0', 'pointer': f'/events/1/pages/0/list/{i}',
             'code': 357, 'plugin': 'P', 'command': 'show', 'approved_fields': ['text'], 'unreviewed_fields': ['id'],
             'raw_commands': [{'parameters': ['P', 'show', '', {'id': f'原文{i}'}]}]} for i in range(6101)]
    dialog = CommandAuditDialog({'dataset_revision': 3, 'documents': [{}], 'records': rows}, 'local.json')
    try:
        assert dialog.model.rowCount() == 6101
        assert dialog.table.editTriggers() == QAbstractItemView.NoEditTriggers and dialog.details.isReadOnly()
        dialog.table.selectRow(6100)
        app.processEvents()
        assert '/events/1/pages/0/list/6100' in dialog.details.toPlainText()
        dialog.filter_edit.setText('原文6100')
        assert dialog.model.rowCount() == 1 and '原文6100' in dialog.details.toPlainText()
        assert not dialog.model.flags(dialog.model.index(0, 0)) & Qt.ItemIsEditable
    finally:
        dialog.close()
