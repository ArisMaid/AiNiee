"""Canonical deterministic checks join existing quality heuristics in one report."""
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Domain.TranslationResultCheck.TranslationResultCheck import TranslationResultCheck
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from test_game_output_policy import case


def settings(path):
    return SimpleNamespace(label_output_path=str(path),exclusion_list_switch=False,
        exclusion_list_data=[],auto_process_text_code_segment=False)


def test_direct_quality_report_refuses_original_or_captured_source(tmp_path):
    store,_,project,source=case(tmp_path)
    try:
        for output in (source,store.root/'source'):
            with pytest.raises(ValueError):TranslationResultCheck().check_cache(settings(output),project)
        assert not (store.root/'source').exists()
        assert list(source.iterdir())==[source/'keep.txt']
    finally:store.close()


def test_canonical_report_ignores_forged_cache_and_includes_deterministic_and_polished_quality(tmp_path):
    store,units,_,_=case(tmp_path)
    try:
        changed=replace(units[0],source_text=chr(92)+'N[1]原文',source_hash='')
        store.replace_units([changed,*units[1:]])
        store.commit(TranslationProposal('u0',chr(92)+'N[1]有效稿',changed.source_hash,2,origin='manual'))
        # Direct legacy-row corruption: the canonical check must still find it.
        store._connection.execute("UPDATE translations SET text='丢失控制符' WHERE unit_id='u0'")
        store.commit(TranslationProposal('u1','示例文本B-1',units[1].source_hash,0,origin='polish'))
        store.set_locked('u1',True)
        project=build_projection(store)
        for item in project.items_iter():item.source_text='forged';item.translated_text='forged';item.translation_status=7
        output=store.root/'AiNieeOutput';before=store.metadata()['content_revision'];jobs=store.jobs()
        result=TranslationResultCheck().check_cache(settings(output),project)
        assert result['passed'] is False
        assert result['project_id']==store.metadata()['project_id']
        assert result['content_revision']==before and result['runtime_validation']=='not_run'
        assert result['deterministic']['passed'] is False and result['deterministic']['issues']
        errors=result['quality']['errors']
        assert any(row['unit_id']=='u1' and any('示例文本' in error for error in row['errors']) for row in errors)
        assert result['quality']['summary']['example_text_errors']==1
        assert store.metadata()['content_revision']==before and store.jobs()==jobs
        assert json.loads(__import__('pathlib').Path(result['report_path']).read_text(encoding='utf-8'))==result
    finally:store.close()


def test_same_second_reports_never_overwrite_each_other(tmp_path):
    store,_,project,_=case(tmp_path);output=store.root/'exports'
    try:
        checker=TranslationResultCheck()
        with patch('time.strftime',return_value='fixed-second'):
            first=checker.check_cache(settings(output),project)
            second=checker.check_cache(settings(output),project)
        assert first['report_path']!=second['report_path']
        assert len(list(output.glob('game-validation-*.json')))==2
        assert not list(output.glob('translation_check_errors_*.json'))
    finally:store.close()


def test_explicit_polish_report_destination_is_used(tmp_path):
    store,_,project,_=case(tmp_path)
    try:
        output=store.root/'AiNieePolishOutput'
        cfg=settings(store.root/'source')
        report=TranslationResultCheck().check_cache(cfg,project,output_path=output)
        assert __import__('pathlib').Path(report['report_path']).parent==output
        assert not (store.root/'source').exists()
    finally:store.close()


@pytest.mark.parametrize('has_root',[True,False])
def test_private_legacy_writer_cannot_bypass_game_report_policy(tmp_path,has_root):
    store,_,project,source=case(tmp_path)
    try:
        if not has_root:project.extra.pop('game_project_root')
        with pytest.raises(ValueError,match='GAME_QUALITY_REPORT_REQUIRED'):
            TranslationResultCheck()._check_cache(settings(source),project)
        assert list(source.iterdir())==[source/'keep.txt']
    finally:store.close()


def test_pending_reset_is_reported_as_scheduling_and_keeps_accepted_quality(tmp_path):
    from test_game_task_reset import manager
    from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
    store,_,project,_=case(tmp_path)
    try:
        assert manager(project).reset_project_status(TaskType.TRANSLATION)==1
        report=TranslationResultCheck().check_cache(settings(store.root/'exports'),project)
        assert report['scheduling']['untranslated']==5
        assert report['deterministic']['untranslated']==4
        assert all(row['unit_id']!='u0' for row in report['quality']['errors'])
    finally:store.close()
