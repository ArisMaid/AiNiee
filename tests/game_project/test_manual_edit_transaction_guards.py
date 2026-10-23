"""Independent guards around explicit manual privilege and metadata-only locks."""
import importlib
import pytest
from ModuleFolders.Domain.GameProject.Models import Issue,Occurrence,TranslationUnit,TranslationProposal,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.TranslationCommitter import TranslationCommitter
from test_manual_edit_atomic_lock import setup


@pytest.mark.parametrize('locked',[None,1])
def test_explicit_manual_api_requires_a_real_boolean(tmp_path,locked):
    store,unit=setup(tmp_path)
    try:
        before=store.translation('unit')
        with pytest.raises(ValueError):
            TranslationCommitter(store).edit_manual(TranslationProposal('unit','新稿',unit.source_hash,
                expected_revision=before['revision'],origin='manual'),locked=locked)
        assert store.translation('unit')==before
    finally:store.close()


@pytest.mark.parametrize('origin',['manual','model'])
def test_ordinary_submission_still_cannot_override_manual_lock(tmp_path,origin):
    store,unit=setup(tmp_path)
    try:
        before=store.translation('unit')
        result=TranslationCommitter(store).submit(TranslationProposal('unit','自动新稿',unit.source_hash,
            expected_revision=before['revision'],origin=origin))
        assert result.status=='locked'
        assert store.translation('unit')==before
    finally:store.close()


@pytest.mark.parametrize('locked',[False,True])
def test_empty_untranslated_row_lock_is_only_metadata(tmp_path,locked):
    store=ProjectStore.create(tmp_path/'project',{'project_id':'empty-lock',
        'engine':'rpgmaker-mz','source_root':str(tmp_path/'source')})
    try:
        text=r'\N[1]菜单'
        unit=TranslationUnit('unit','menu',text,occurrences=(
            Occurrence('occ','data/System.json',{'pointer':'/gameTitle'},hash_text(text)),))
        store.replace_units([unit])
        result=TranslationCommitter(store).edit_manual(TranslationProposal('unit','',unit.source_hash,
            expected_revision=0,origin='manual'),locked=locked)
        assert result.status in {'accepted','duplicate'}
        assert not any(issue.severity in {'error','fatal'} for issue in result.issues)
        tr=store.translation('unit')
        if locked:assert tr['text']=='' and tr['revision']==0 and tr['manual_locked'] and tr['status']=='untranslated'
        else:assert tr is None
        assert store._connection.execute('SELECT count(*) FROM edits').fetchone()[0]==0
    finally:store.close()


def test_stale_identical_text_is_reapproved_under_current_source(tmp_path):
    store,unit=setup(tmp_path)
    try:
        text='新原文'
        changed=TranslationUnit('unit','menu',text,scene_id='menu',occurrences=(
            Occurrence('occ','data/System.json',{'pointer':'/gameTitle'},hash_text(text)),))
        store.replace_units([changed]);before=store.translation('unit');assert before['stale']
        result=TranslationCommitter(store).edit_manual(TranslationProposal('unit',before['text'],changed.source_hash,
            expected_revision=before['revision'],origin='manual'),locked=True)
        assert result.status=='accepted' and result.revision==before['revision']+1
        tr=store.translation('unit')
        assert tr['source_hash']==changed.source_hash and not tr['stale'] and tr['manual_locked']
    finally:store.close()


@pytest.mark.parametrize('conflict',['source','revision'])
def test_lock_only_command_does_not_bypass_source_or_revision_cas(tmp_path,conflict):
    store,unit=setup(tmp_path)
    try:
        before=store.translation('unit');content_revision=store.metadata()['content_revision']
        result=TranslationCommitter(store).edit_manual(TranslationProposal('unit',before['text'],
            '0'*64 if conflict=='source' else unit.source_hash,
            expected_revision=0 if conflict=='revision' else before['revision'],origin='manual'),locked=False)
        assert result.status=='conflict'
        assert store.translation('unit')==before and store.metadata()['content_revision']==content_revision
    finally:store.close()


def test_audit_insert_failure_rolls_back_text_and_lock_together(tmp_path,monkeypatch):
    store,unit=setup(tmp_path)
    try:
        before=store.translation('unit');content_revision=store.metadata()['content_revision']
        module=importlib.import_module('ModuleFolders.Service.GameProject.ProjectStore')
        def fail(*args,**kwargs):raise RuntimeError('controlled proposal audit failure')
        monkeypatch.setattr(module,'_insert_proposal',fail)
        with pytest.raises(RuntimeError,match='controlled proposal audit failure'):
            TranslationCommitter(store).edit_manual(TranslationProposal('unit','新稿',unit.source_hash,
                expected_revision=before['revision'],origin='manual'),locked=False)
        assert store.translation('unit')==before and store.metadata()['content_revision']==content_revision
    finally:store.close()


def test_metadata_only_command_respects_explicit_blocking_issue(tmp_path):
    store,unit=setup(tmp_path)
    try:
        before=store.translation('unit');revision=store.metadata()['content_revision']
        proposal=TranslationProposal('unit',before['text'],unit.source_hash,
            expected_revision=before['revision'],origin='manual')
        result=store.commit(proposal,manual_lock=False,issues=[
            Issue('CANCELLED_REQUEST','error','controlled cancelled command','unit')])
        assert result.status=='rejected'
        assert store.translation('unit')==before and store.metadata()['content_revision']==revision
    finally:store.close()
