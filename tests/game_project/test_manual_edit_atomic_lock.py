"""Codex-owned actual GUI command boundary: text and requested lock are atomic."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from ModuleFolders.Domain.GameProject.Models import Occurrence,TranslationUnit,TranslationProposal,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Infrastructure.Platform.OwnedProcess import run as owned_run


def setup(tmp_path,source='原文',text='人工原稿',locked=True):
    store=ProjectStore.create(tmp_path/'project',{'project_id':'atomic-edit',
        'engine':'rpgmaker-mz','source_root':str(tmp_path/'source')})
    unit=TranslationUnit('unit','menu',source,scene_id='menu',occurrences=(
        Occurrence('occ','data/System.json',{'pointer':'/gameTitle'},hash_text(source)),))
    store.replace_units([unit]);store.commit(TranslationProposal('unit',text,unit.source_hash,origin='manual'))
    store.set_locked('unit',locked)
    return store,unit


def edit(store,unit,text,lock):
    from UserInterface.GameProject.GameProjectPage import _GameProjectJob
    tr=store.translation(unit.unit_id)
    payload={'row':{'unit_id':unit.unit_id,'source_hash':unit.source_hash,
        'expected_revision':tr['revision'],'text':text},'lock':lock}
    return _GameProjectJob._commit_unit(SimpleNamespace(_payload=payload),SimpleNamespace(store=store))


def test_locked_text_and_requested_lock_use_one_writer_transaction(tmp_path):
    store,unit=setup(tmp_path)
    try:
        before=store.translation('unit');trace=[];store._connection.set_trace_callback(trace.append)
        result=edit(store,unit,'人工新稿',True)
        store._connection.set_trace_callback(None)
        assert result['results'][0]['status']=='accepted'
        tr=store.translation('unit')
        assert tr['text']=='人工新稿' and tr['manual_locked']
        assert tr['revision']==before['revision']+1
        assert sum(s.strip().upper()=='BEGIN IMMEDIATE' for s in trace)==1
        assert sum(s.strip().upper()=='COMMIT' for s in trace)==1
    finally:store.close()


def test_rejected_manual_edit_does_not_toggle_lock_or_content_revision(tmp_path):
    store,unit=setup(tmp_path,source=r'\N[1]原文',text=r'\N[1]人工原稿')
    try:
        before=store.translation('unit');revision=store.metadata()['content_revision']
        result=edit(store,unit,'损坏控制符',False)
        assert result['results'][0]['status']=='rejected'
        assert store.translation('unit')==before
        assert store.metadata()['content_revision']==revision
    finally:store.close()


def test_unchanged_text_lock_only_does_not_create_an_accepted_edit(tmp_path):
    store,unit=setup(tmp_path,locked=False)
    try:
        before=store.translation('unit')
        accepted=store._connection.execute("SELECT count(*) FROM edits").fetchone()[0]
        result=edit(store,unit,'人工原稿',True)
        assert result['results']==[] and result['changed']
        assert store.translation('unit')['revision']==before['revision']
        assert store.translation('unit')['manual_locked']
        assert store._connection.execute("SELECT count(*) FROM edits").fetchone()[0]==accepted
    finally:store.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Owned Windows child crash proof')
def test_actual_process_exit_mid_text_update_preserves_original_manual_lock(tmp_path):
    store,unit=setup(tmp_path);root=store.root;before=store.translation('unit');store.close()
    repo=Path(__file__).resolve().parents[2]
    code='''import json,os,sys
from types import SimpleNamespace
from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
configure_qt_paths()
from PyQt5.QtWidgets import QApplication
app=QApplication([])
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from UserInterface.GameProject.GameProjectPage import _GameProjectJob
with ProjectStore(sys.argv[1]) as store:
    unit=store.unit('unit');tr=store.translation('unit')
    def trace(sql):
        if sql.strip().lower().startswith('update translations set text'):
            os._exit(77)
    store._connection.set_trace_callback(trace)
    payload={'row':{'unit_id':'unit','source_hash':unit.source_hash,'expected_revision':tr['revision'],'text':'manual new text'},'lock':True}
    _GameProjectJob._commit_unit(SimpleNamespace(_payload=payload),SimpleNamespace(store=store))
raise RuntimeError('Fixture did not reach text update')
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',PYTHONPATH=str(repo),PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',AINIEE_OFFLINE='1')
    response=owned_run([sys.executable,'-c',code,str(root)],cwd=repo,env=env,input=b'',timeout=30)
    (tmp_path/'crash.stdout').write_bytes(response.stdout);(tmp_path/'crash.stderr').write_bytes(response.stderr)
    assert response.returncode==77,response.stderr[-1500:]
    with ProjectStore(root) as reopened:
        assert reopened.translation('unit')==before
