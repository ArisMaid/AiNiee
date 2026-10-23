"""Explicit user resets persist without clearing accepted text or bypassing CAS."""
from dataclasses import replace
import importlib,json,os,sys,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest

from ModuleFolders.Base.Base import Base
from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.CacheBridge import build_projection,refresh_projection
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner
from ModuleFolders.Service.Cache.CacheManager import CacheManager
from ModuleFolders.Service.Cache.CacheItem import CacheItem,TranslationStatus
from ModuleFolders.Service.Cache.CacheFile import CacheFile
from ModuleFolders.Service.Cache.CacheProject import CacheProject
from test_game_batch_preparation import create,config,Requester


def manager(project):
    host=object.__new__(CacheManager);host.project=project
    host.file_lock=threading.Lock();host.save_to_file=Mock()
    return host


def seed(tmp_path):
    store,units,_=create(tmp_path)
    for index,origin in [(0,'manual'),(1,'polish'),(2,'polish')]:
        store.commit(TranslationProposal(f'u{index}',f'批准译文{index}',units[index].source_hash,0,origin=origin))
    store.set_locked('u2',True)
    return store,units,manager(build_projection(store))


def by_id(project):return {item.get_extra('unit_id'):item for item in project.items_iter()}


def authority(store):
    return {table:[tuple(row) for row in store._connection.execute(f'SELECT * FROM {table}')]
        for table in ('translations','proposals','edits','metadata')}


@pytest.mark.parametrize('mode,changed',[(TaskType.TRANSLATION,2),(TaskType.POLISH,1)])
def test_reset_survives_reload_keeps_text_lock_audit_and_advances_revision(tmp_path,mode,changed):
    store,units,host=seed(tmp_path)
    try:
        before={u.unit_id:store.translation(u.unit_id) for u in units}
        old_meta=store.metadata();old_edits=len(store.edits());trace=[]
        store._connection.set_trace_callback(trace.append)
        # Exercise the real cache entry; it must not depend on legacy JSON cache saving.
        assert host.reset_project_status(mode)==changed
        store._connection.set_trace_callback(None)
        fresh=refresh_projection(host.project);rows=by_id(fresh)
        origin='reset-translate' if mode==TaskType.TRANSLATION else 'reset-polish'
        targets=['u0','u1'] if mode==TaskType.TRANSLATION else ['u1']
        for unit_id in targets:
            current=store.translation(unit_id)
            assert current['text']==before[unit_id]['text']
            assert current['source_hash']==before[unit_id]['source_hash']
            assert current['revision']==before[unit_id]['revision']+1
            assert current['origin']==origin
            assert rows[unit_id].translation_status==(
                TranslationStatus.UNTRANSLATED if mode==TaskType.TRANSLATION else TranslationStatus.TRANSLATED)
            assert rows[unit_id].translated_text==before[unit_id]['text']
        assert store.translation('u2')==before['u2'] and rows['u2'].translation_status==TranslationStatus.EXCLUDED
        assert store.translation('u3') is None
        assert store.metadata()['dataset_revision']==old_meta['dataset_revision']
        assert store.metadata()['content_revision']==old_meta['content_revision']+1
        assert len(store.edits())==old_edits+changed
        assert not host.save_to_file.called
        # No second reset of the same pending operation and no extra audit rows.
        after=authority(store)
        assert host.reset_project_status(mode)==0 and authority(store)==after
    finally:store.close()


def test_cache_forged_status_does_not_schedule_a_new_canonical_reset(tmp_path):
    store,units,host=seed(tmp_path)
    try:
        by_id(host.project)['u0'].translation_status=TranslationStatus.POLISHED
        assert host.reset_project_status(TaskType.POLISH)==1
        assert store.translation('u0')['origin']=='manual'
        assert store.translation('u1')['origin']=='reset-polish'
    finally:store.close()


def test_reset_refresh_preserves_canonical_unknown_control_exclusion(tmp_path):
    store,units,host=seed(tmp_path)
    try:
        blocked=replace(units[4],source_text='原文'+chr(92)+'Unknown[1]',source_hash='')
        store.replace_units([*units[:4],blocked]);host.project=build_projection(store)
        before=by_id(host.project)['u4']
        assert before.translation_status==TranslationStatus.EXCLUDED
        assert host.reset_project_status(TaskType.TRANSLATION)==2
        assert by_id(host.project)['u4'].translation_status==TranslationStatus.EXCLUDED
        assert by_id(host.project)['u4'].get_extra('blocked_token_codes')
    finally:store.close()


@pytest.mark.parametrize('origin',['reset-translate','reset-polish'])
def test_ordinary_commit_cannot_forge_an_explicit_reset_operation(tmp_path,origin):
    store,units,_=seed(tmp_path)
    try:
        before=authority(store)
        with pytest.raises(ValueError,match='reset_task_status'):
            store.commit(TranslationProposal('u0','批准译文0',units[0].source_hash,1,origin=origin))
        assert authority(store)==before
    finally:store.close()


def test_explicit_reset_and_all_audit_rows_use_one_writer_transaction(tmp_path):
    from contextlib import contextmanager
    store,_,host=seed(tmp_path);trace=[];original=ProjectStore._write
    @contextmanager
    def traced(connection):
        connection._connection.set_trace_callback(trace.append)
        with original(connection) as writer:yield writer
    try:
        with patch.object(ProjectStore,'_write',traced):
            assert host.reset_project_status(TaskType.TRANSLATION)==2
        assert sum(sql.strip().upper()=='BEGIN IMMEDIATE' for sql in trace)==1
        assert sum(sql.strip().upper()=='COMMIT' for sql in trace)==1
    finally:store.close()


@pytest.mark.parametrize('forgery',['revision','source_hash','root','project_id','dataset','missing_item','duplicate_item'])
def test_stale_or_forged_projection_rejects_entire_reset_before_any_mutation(tmp_path,forgery):
    store,units,host=seed(tmp_path)
    try:
        items=by_id(host.project)
        if forgery=='revision':items['u1'].set_extra('translation_revision',0)
        elif forgery=='source_hash':items['u1'].set_extra('source_hash','0'*64)
        elif forgery=='root':items['u1'].set_extra('game_project_root',str(tmp_path/'foreign'))
        elif forgery=='project_id':host.project.project_id='foreign-project'
        elif forgery=='dataset':items['u1'].set_extra('dataset_revision',0)
        elif forgery=='missing_item':host.project.get_file('data/Map001.json').items.pop()
        else:host.project.get_file('data/Map001.json').items.append(items['u0'])
        before=authority(store)
        with pytest.raises(ValueError):host.reset_project_status(TaskType.TRANSLATION)
        assert authority(store)==before
    finally:store.close()


def test_audit_failure_rolls_back_all_units_and_content_revision(tmp_path):
    store,_,host=seed(tmp_path)
    try:
        store._connection.execute("CREATE TRIGGER fail_reset BEFORE INSERT ON edits WHEN NEW.unit_id='u1' AND NEW.origin='reset-translate' BEGIN SELECT RAISE(ABORT,'reset audit fault'); END")
        before=authority(store);cache_before=[item.translation_status for item in host.project.items_iter()]
        with pytest.raises(ValueError,match='reset audit fault'):host.reset_project_status(TaskType.TRANSLATION)
        assert authority(store)==before
        assert [item.translation_status for item in host.project.items_iter()]==cache_before
    finally:store.close()


def test_pre_reset_late_result_conflicts_and_fresh_request_replaces_pending_state(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,host=seed(tmp_path)
    try:
        old=GameBatchRunner([by_id(host.project)['u0']],config())
        assert host.reset_project_status(TaskType.TRANSLATION)==2
        requester=Requester();late=old.run(requester)
        assert not late['check_result'] and store.translation('u0')['origin']=='reset-translate'
        assert store.translation('u0')['text']=='批准译文0'
        fresh=GameBatchRunner([by_id(host.project)['u0']],config())
        assert fresh.run(Requester())['check_result']
        assert store.translation('u0')['origin']=='translate'
        assert by_id(refresh_projection(host.project))['u0'].translation_status==TranslationStatus.TRANSLATED
    finally:store.close()


def test_pending_translation_is_not_a_polish_target_and_new_acceptance_clears_reset(tmp_path):
    store,units,host=seed(tmp_path)
    try:
        assert host.reset_project_status(TaskType.TRANSLATION)==2
        chunks,_,_=host.generate_item_chunks('line',20,2,TaskType.POLISH)
        assert chunks==[]
        revision=store.translation('u0')['revision']
        store.commit(TranslationProposal('u0','新的人工稿',units[0].source_hash,revision,origin='manual'))
        assert by_id(refresh_projection(host.project))['u0'].translation_status==TranslationStatus.TRANSLATED
    finally:store.close()


@pytest.mark.parametrize('mode',[True,'1000',None,1001])
def test_invalid_game_reset_mode_changes_nothing(tmp_path,mode):
    store,_,host=seed(tmp_path)
    try:
        before=authority(store)
        with pytest.raises(ValueError):host.reset_project_status(mode)
        assert authority(store)==before
    finally:store.close()


def test_ordinary_document_reset_keeps_legacy_cache_save(tmp_path):
    project=CacheProject(project_type='Txt');file=CacheFile(storage_path='document.txt')
    file.add_item(CacheItem(source_text='source',translated_text='translation',translation_status=TranslationStatus.TRANSLATED))
    project.add_file(file);host=manager(project)
    assert host.reset_project_status(TaskType.TRANSLATION)==1
    assert file.items[0].translated_text=='translation'
    assert file.items[0].translation_status==TranslationStatus.UNTRANSLATED
    host.save_to_file.assert_called_once()


@pytest.mark.parametrize('confirmed',[True,False])
def test_real_ui_reset_command_respects_confirmation_and_reports_stale_cache(tmp_path,monkeypatch,confirmed):
    module=importlib.import_module('UserInterface.EditView.Translation.BottomCommandBar')
    store,_,host=seed(tmp_path)
    dialog=SimpleNamespace(yesButton=Mock(),cancelButton=Mock(),exec=lambda:confirmed)
    monkeypatch.setattr(module,'MessageBox',lambda *_:dialog)
    page=SimpleNamespace(_can_reset_project=lambda **_:True,_update_reset_button_state=lambda:None,
        tra=lambda value:value,window=lambda:None,cache_manager=host,info_toast=Mock(),
        error_toast=Mock(),success_toast=Mock(),emit=Mock(),update_task_action_button=Mock())
    try:
        if confirmed:by_id(host.project)['u1'].set_extra('translation_revision',0)
        before=authority(store)
        module.BottomCommandBar.command_reset_status(page,TaskType.TRANSLATION)
        assert authority(store)==before and not page.success_toast.called
        if confirmed:page.error_toast.assert_called_once()
        else:assert not page.error_toast.called
    finally:store.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Owned Windows crash proof')
def test_process_exit_between_reset_rows_rolls_back_the_whole_operation(tmp_path):
    from ModuleFolders.Infrastructure.Platform.OwnedProcess import run as owned_run
    store,_,_=seed(tmp_path);before=authority(store);root=store.root;store.close()
    repo=Path(__file__).resolve().parents[2]
    code='''import os,sys,threading
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.Cache.CacheManager import CacheManager
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
actual=ProjectStore._write
from contextlib import contextmanager
@contextmanager
def traced(self):
    count=0
    def trace(sql):
        nonlocal count
        if sql.strip().lower().startswith('update translations set revision'):
            count+=1
            if count==2:os._exit(78)
    self._connection.set_trace_callback(trace)
    with actual(self) as connection:yield connection
ProjectStore._write=traced
with ProjectStore(sys.argv[1]) as store:
    host=object.__new__(CacheManager);host.project=build_projection(store);host.file_lock=threading.Lock()
    host.save_to_file=lambda:None
    host.reset_project_status(TaskType.TRANSLATION)
raise RuntimeError('Reset crash boundary was not reached')
'''
    env=dict(os.environ,PYTHONPATH=str(repo),PYTHONIOENCODING='utf-8',AINIEE_OFFLINE='1')
    result=owned_run([sys.executable,'-c',code,str(root)],cwd=repo,env=env,input=b'',timeout=30)
    (tmp_path/'reset-crash.stdout').write_bytes(result.stdout);(tmp_path/'reset-crash.stderr').write_bytes(result.stderr)
    assert result.returncode==78,result.stderr.decode('utf-8',errors='replace')
    with ProjectStore(root) as reopened:assert authority(reopened)==before
