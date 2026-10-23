import json
from pathlib import Path
import tempfile
import subprocess
import sys
from dataclasses import replace

import pytest
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.MigrationWorkflow import prepare_review,apply_review,reconciliation_rows
from ModuleFolders.Service.GameProject.BuildService import file_hash


@pytest.fixture
def projects():
    base=Path(__file__).resolve().parents[2]/'work/acceptance';base.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='migration-review-',dir=base));source=root/'game'
    (source/'data').mkdir(parents=True);(source/'js').mkdir()
    (source/'index.html').write_text('<script src="js/rpg_core.js"></script>',encoding='utf-8')
    (source/'js/rpg_core.js').write_text('// rpg_core.js v1.6.2',encoding='utf-8')
    (source/'data/System.json').write_text(json.dumps({'gameTitle':'テスト','terms':{'save':'保存'}},ensure_ascii=False),encoding='utf-8')
    with GameProjectService.create(source,root/'old') as old,GameProjectService.create(source,root/'new') as new:
        old.extract();new.extract()
        uid=next(u.unit_id for u in old.store.units() if u.source_text=='保存')
        assert old.import_translations({uid:'存档'})[0].status=='accepted'
        yield old,new,uid


def test_unverified_plan_is_readable_but_not_applicable(projects):
    old,new,uid=projects
    envelope=prepare_review(old.store.root,new.store.root)
    assert not envelope['plan']['identity']['verified'] and envelope['plan']['matches']==[]
    assert len(reconciliation_rows(envelope))>=len(new.store.units())
    with pytest.raises(ValueError,match='MIGRATION_IDENTITY_UNVERIFIED'):
        apply_review(new.store.root,envelope['plan_id'])
    assert new.store.translation(uid) is None


def test_explicit_lineage_and_review_use_readonly_source_with_live_wal(projects):
    old,new,uid=projects
    old_meta=old.store.metadata();old_db=file_hash(old.store.root/'project.sqlite3')
    wal=old.store.root/'project.sqlite3-wal';before_wal=file_hash(wal) if wal.exists() else None
    envelope=prepare_review(old.store.root,new.store.root,confirm_lineage=True)
    assert envelope['plan']['identity']['verified']
    assert envelope['plan']['identity']['verification_method']=='explicit_lineage'
    assert len(envelope['plan']['matches'])==1
    assert len(reconciliation_rows(envelope,'reused'))==1
    assert old.store.metadata()==old_meta and file_hash(old.store.root/'project.sqlite3')==old_db
    if before_wal is not None:assert file_hash(wal)==before_wal
    result=apply_review(new.store.root,envelope['plan_id'])
    assert result['accepted']==1 and result['rejected']==0
    assert new.store.translation(uid)['text']=='存档'
    revision=new.store.translation(uid)['revision']
    with pytest.raises(ValueError,match='MIGRATION_REVIEW_ALREADY_APPLIED'):
        apply_review(new.store.root,envelope['plan_id'])
    assert new.store.translation(uid)['revision']==revision


def test_review_rejects_edits_and_file_tampering_before_writing(projects):
    old,new,uid=projects
    envelope=prepare_review(old.store.root,new.store.root,confirm_lineage=True)
    assert new.import_translations({uid:'人工新稿'})[0].status=='accepted'
    new.store.set_locked(uid,True);before=new.store.translation(uid)
    with pytest.raises(ValueError,match='MIGRATION_REVIEW_STALE'):apply_review(new.store.root,envelope['plan_id'])
    assert new.store.translation(uid)==before
    other=prepare_review(old.store.root,new.store.root)
    Path(other['plan_path']).write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='MIGRATION_REVIEW_TAMPERED'):apply_review(new.store.root,other['plan_id'])
    assert new.store.translation(uid)==before


def test_confirm_lineage_cli_does_not_guess_and_does_not_modify_old_project(projects):
    old,new,uid=projects
    root=Path(__file__).resolve().parents[2]
    code=subprocess.run([sys.executable,'RpgApp.py','--cli','migrate','--old-project',str(old.store.root),
        '--project',str(new.store.root),'--confirm-lineage','--apply'],cwd=root,capture_output=True,timeout=20)
    assert code.returncode==0,code.stderr
    result=json.loads(code.stdout.decode('utf-8'))
    assert result['identity']['verified'] and result['identity']['verification_method']=='explicit_lineage'
    assert result['results'][0]['status']=='accepted'
    assert new.store.translation(uid)['text']=='存档'


def test_fresh_migration_can_revalidate_a_translation_after_source_changed_back(projects):
    from ModuleFolders.Service.GameProject.MigrationService import plan_migration,apply_migration
    from ModuleFolders.Domain.GameProject.Models import hash_text
    old,new,uid=projects
    envelope=prepare_review(old.store.root,new.store.root,confirm_lineage=True)
    apply_review(new.store.root,envelope['plan_id'])
    original=new.store.units()
    changed=[]
    for unit in original:
        if unit.unit_id==uid:
            unit=replace(unit,source_text='一时不同',source_hash='',occurrences=tuple(
                replace(o,expected_value_hash=hash_text('一时不同')) for o in unit.occurrences))
        changed.append(unit)
    new.store.replace_units(changed);new.store.replace_units(original)
    assert new.store.translation(uid)['stale']
    plan=plan_migration(old.store,new.store);assert len(plan['matches'])==1
    results=apply_migration(old.store,new.store,plan)
    assert results[0].status=='accepted'
    assert not new.store.translation(uid)['stale']


def test_review_and_apply_cli_preserve_a_concrete_approved_plan(projects):
    old,new,uid=projects;root=Path(__file__).resolve().parents[2]
    reviewed=subprocess.run([sys.executable,'RpgApp.py','--cli','migration-review','--old-project',str(old.store.root),
        '--project',str(new.store.root),'--confirm-lineage'],cwd=root,capture_output=True,timeout=20)
    assert reviewed.returncode==0,reviewed.stderr
    payload=json.loads(reviewed.stdout.decode('utf-8'));assert payload['stats']['match_count']==1
    applied=subprocess.run([sys.executable,'RpgApp.py','--cli','migration-apply-review','--project',str(new.store.root),
        '--plan-id',payload['plan_id']],cwd=root,capture_output=True,timeout=20)
    assert applied.returncode==0,applied.stderr
    assert json.loads(applied.stdout.decode('utf-8'))['accepted']==1
    assert new.store.translation(uid)['text']=='存档'
