import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtWidgets import QApplication,QAbstractItemView
from PyQt5.QtCore import Qt
from UserInterface.GameProject.ComparisonReportDialog import ComparisonReportDialog

APP=QApplication.instance() or QApplication([])


def report():
    return {'backend':'rpgmtl','relative_path':'data/Items.json','report_path':'local-report.json',
        'counts':{'overlap':1,'backend_only':1,'ambiguous':6500,'native_only':1},
        'overlap':[{'unit_id':'u','record_index':6500,'pointer':'/1/name'}],
        'backend_only':[{'record_index':6501,'candidate_pointers':[]}],
        'ambiguous':[{'record_index':i,'candidate_pointer_group':'g0','candidate_pointer_count':2000} for i in range(6500)],
        'native_only':[{'unit_id':'native-only','pointer':'/2/name'}],
        'candidate_pointer_groups':{'g0':[f'/{i}/description' for i in range(2000)]},
        'backend_records':[{'record_index':i,'text':f'候选{i}','locator':{'group_index':i}} for i in range(6502)],
        'native_occurrences':[{'unit_id':'u','pointer':'/1/name','role':'name','kind':'menu','value_codec':None,'source_text':'名称',
            'source_hash':'a'*64,'expected_value_hash':'a'*64},{'unit_id':'native-only','pointer':'/2/name',
            'role':'dialogue','kind':'dialogue','value_codec':'event-js-json-string-v1','source_text':'原生文字','source_hash':'b'*64,'expected_value_hash':'c'*64}]}


def test_all_rows_filter_group_pointers_selection_and_no_write_authority():
    data=report();before=copy.deepcopy(data);dialog=ComparisonReportDialog(data)
    try:
        assert dialog.model.rowCount()==6503
        assert dialog.table.editTriggers()==QAbstractItemView.NoEditTriggers and dialog.details.isReadOnly()
        assert not dialog.model.flags(dialog.model.index(0,0)) & Qt.ItemIsEditable
        dialog.filter_edit.setText('候选6499');APP.processEvents()
        assert dialog.model.rowCount()==1 and '候选6499' in dialog.details.toPlainText()
        selected=json.loads(dialog.details.toPlainText().split('\n\n')[0])
        assert 'g0' in json.dumps(selected,ensure_ascii=False)
        assert len(dialog.details.toPlainText())<18000
        assert 'pointer_preview_truncated' in dialog.details.toPlainText()
        dialog.filter_edit.setText('/1999/description');APP.processEvents()
        assert dialog.model.rowCount()==6500
        dialog.filter_edit.setText('原生文字');APP.processEvents()
        assert dialog.model.rowCount()==1 and 'event-js-json-string-v1' in dialog.details.toPlainText()
        dialog.filter_edit.clear();APP.processEvents()
        assert dialog.model.rowCount()==6503
        assert data==before
    finally:dialog.close()


def test_old_report_preserves_available_locations_without_annotations():
    data=report();data.pop('backend_records');data.pop('native_occurrences')
    dialog=ComparisonReportDialog(data)
    try:
        assert dialog.model.rowCount()==6503
        assert '/1/name' in dialog.details.toPlainText()
    finally:dialog.close()
