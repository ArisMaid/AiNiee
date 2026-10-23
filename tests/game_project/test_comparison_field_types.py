import copy
import pytest
from ModuleFolders.Service.GameProject.CoverageComparison import compare_extractions
from ModuleFolders.Infrastructure.GameAdapters.ExtractionPointerPool import pack_records


def test_actual_field_types_and_unresolved_positions_are_reference_conflicts():
    document={'string':'text','number':1,'boolean':False,'null':None,'array':[],'object':{}}
    native=[{'unit_id':'n','source_text':'old text','kind':'menu','occurrences':[
        {'relative_path':'data/Test.json','locator':{'pointer':'/number'},'role':'name'}]}]
    pointers=['/string','/number','/boolean','/null','/array','/object','/missing']
    backend={'ok':True,'records':[{'text':'claimed text','locator':{},'candidate_pointers':pointers}]}
    before=copy.deepcopy((native,backend,document))
    result=compare_extractions(native,backend,'data/Test.json',document=document)
    assert (native,backend,document)==before
    assert result['type_check']=='complete' and result['type_conflict_count']==2
    assert result['type_conflict_pointer_count']==6
    assert result['source_field_types']=={'/number':'number','/boolean':'boolean','/null':'null','/array':'array','/object':'object','/missing':'unresolved'}
    assert result['counts']['ambiguous']==1
    assert result['type_conflicts'][0]['side']=='native'
    backend_conflict=result['type_conflicts'][1]
    assert result['candidate_pointer_groups'][backend_conflict['candidate_pointer_group']]==pointers[1:]


def test_shared_conflict_groups_are_not_expanded_per_backend_record():
    from unittest.mock import patch
    from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import resolve_pointer
    pointers=[f'/{i}' for i in range(2000)]
    backend={'ok':True,**pack_records([{'text':'same','locator':{},'candidate_pointers':pointers} for _ in range(2000)])}
    with patch('ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher.resolve_pointer', wraps=resolve_pointer) as resolver:
        result=compare_extractions([],backend,'data/Test.json',document=[1]*2000)
    assert resolver.call_count==2000
    assert result['type_conflict_count']==2000 and result['type_conflict_pointer_count']==2000
    assert len(result['candidate_pointer_groups'])==2
    assert len({row['candidate_pointer_group'] for row in result['type_conflicts']})==1
    assert all('candidate_pointers' not in row for row in result['type_conflicts'])


def test_encoded_string_is_not_a_type_conflict_and_absent_document_is_explicit():
    backend={'ok':True,'records':[{'text':'"表示"','locator':{},'candidate_pointers':['/literal']}]}
    checked=compare_extractions([],backend,'data/Test.json',document={'literal':'"表示"'})
    assert checked['type_check']=='complete' and checked['type_conflict_count']==0
    assert compare_extractions([],backend,'data/Test.json')['type_check']=='unavailable'
    assert compare_extractions([],{'ok':True,'records':[]},'data/Test.json',document=None)['type_check']=='complete'


def test_type_conflicts_are_locatable_in_the_readonly_viewer(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
    configure_qt_paths()
    from PyQt5.QtWidgets import QApplication
    from UserInterface.GameProject.ComparisonReportDialog import ComparisonReportDialog
    app=QApplication.instance() or QApplication([])
    native=[{'unit_id':'n','source_text':'old','kind':'menu','occurrences':[
        {'relative_path':'data/Test.json','locator':{'pointer':'/number'},'role':'name'}]}]
    result=compare_extractions(native,{'ok':True,'records':[{'text':'text','locator':{},'candidate_pointers':['/number']}]},
        'data/Test.json',document={'number':1})
    dialog=ComparisonReportDialog(result)
    try:
        dialog.filter_edit.setText('字段类型冲突');app.processEvents()
        assert dialog.model.rowCount()==2
        assert 'number' in dialog.details.toPlainText() and 'source_field_types' in dialog.details.toPlainText()
    finally:dialog.close()
