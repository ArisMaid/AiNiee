"""Owner acceptance: real output entrypoints reject before conversion/provider."""
import importlib,json,os,subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Domain.FileOutputer.FileOutputer import FileOutputer
from ModuleFolders.Service.Cache.CacheProject import CacheProject
from test_game_batch_preparation import create


def policy(project,output):
    from ModuleFolders.Service.GameProject.GameOutputPolicy import preflight_game_output
    return preflight_game_output(project,output)


def case(tmp_path):
    store,units,_=create(tmp_path)
    source=tmp_path/'source';source.mkdir();(source/'keep.txt').write_text('source stays',encoding='utf-8')
    store.commit(TranslationProposal('u0','繁體原稿',units[0].source_hash,0,origin='manual'))
    return store,units,build_projection(store),source


@pytest.mark.parametrize('relative',['source','jobs','migrations','validations','builds','extractions','custom',''])
def test_direct_game_writer_cannot_export_into_project_authority_folders(tmp_path,relative):
    store,_,project,source=case(tmp_path)
    output=store.root/relative;before=list(store.root.rglob('*.json'))
    try:
        with pytest.raises(ValueError):
            FileOutputer().output_translated_content(project,output,'unused',{})
        assert list(store.root.rglob('*.json'))==before
        if relative:assert not output.exists()
        assert (source/'keep.txt').read_text(encoding='utf-8')=='source stays'
    finally:store.close()


@pytest.mark.parametrize('target',['source','source-child','ancestor'])
def test_original_game_root_and_overlapping_roots_are_refused(tmp_path,target):
    store,_,project,source=case(tmp_path)
    try:
        output={'source':source,'source-child':source/'new-output','ancestor':tmp_path}[target]
        with pytest.raises(ValueError):policy(project,output)
        assert list(source.iterdir())==[source/'keep.txt']
    finally:store.close()


@pytest.mark.parametrize('relative',['AiNieeOutput','AiNieePolishOutput','exports/subdir'])
def test_managed_defaults_and_exports_work_without_preflight_mkdir(tmp_path,relative):
    store,_,project,_=case(tmp_path);output=store.root/relative
    try:
        assert policy(project,output)==output
        assert not output.exists()
        FileOutputer().output_translated_content(project,output,'unused',{})
        files=list(output.iterdir())
        assert len(files)==1 and files[0].name.startswith('game-translations-')
        payload=json.loads(files[0].read_text(encoding='utf-8'))
        assert next(row for row in payload if row['unit_id']=='u0')['text']=='繁體原稿'
    finally:store.close()


@pytest.mark.parametrize('value',[None,'','   ',b'output'])
def test_empty_or_wrong_type_game_destination_is_rejected(tmp_path,value):
    store,_,project,_=case(tmp_path)
    try:
        with pytest.raises(ValueError):policy(project,value)
    finally:store.close()


def test_external_output_and_ordinary_document_policy(tmp_path):
    store,_,project,_=case(tmp_path);output=tmp_path/'independent-output'
    try:
        assert policy(project,output)==output and not output.exists()
        assert policy(CacheProject(project_type='Txt'),None) is None
        project.project_id='wrong-project'
        with pytest.raises(ValueError,match='IDENTITY|PROJECT'):policy(project,output)
        assert not output.exists()
    finally:store.close()


@pytest.mark.parametrize('damage',['missing_project_root','missing_item_root','foreign_item_root'])
@pytest.mark.parametrize('entry',['exchange','quality'])
def test_incomplete_or_mixed_game_identity_never_falls_back_to_document_output(tmp_path,damage,entry):
    from ModuleFolders.Domain.TranslationResultCheck.TranslationResultCheck import TranslationResultCheck
    store,_,project,_=case(tmp_path);output=tmp_path/'independent-output'
    try:
        if damage=='missing_project_root':project.extra.pop('game_project_root')
        else:
            first=next(project.items_iter())
            if damage=='missing_item_root':first.extra.pop('game_project_root')
            else:first.set_extra('game_project_root',str(tmp_path/'foreign'))
        with pytest.raises(ValueError):
            if entry=='exchange':FileOutputer().output_translated_content(project,output,'unused',{})
            else:
                cfg=SimpleNamespace(label_output_path=str(output),exclusion_list_switch=False,auto_process_text_code_segment=False)
                TranslationResultCheck().check_cache(cfg,project)
        assert not output.exists()
    finally:store.close()


def test_game_json_publication_does_not_overwrite_an_existing_owned_name(tmp_path):
    from ModuleFolders.Service.GameProject.GameOutputPolicy import write_game_json
    store,_,project,_=case(tmp_path);output=store.root/'exports';output.mkdir()
    identifier='a'*32;target=output/f'game-translations-{identifier}.json';target.write_bytes(b'keep')
    try:
        with pytest.raises(FileExistsError):write_game_json(project,output,'game-translations',[],output_id=identifier)
        assert target.read_bytes()==b'keep' and list(output.iterdir())==[target]
    finally:store.close()


def test_empty_item_root_cannot_resolve_as_the_current_project_directory(tmp_path,monkeypatch):
    store,_,project,_=case(tmp_path)
    monkeypatch.chdir(store.root)
    next(project.items_iter()).set_extra('game_project_root','')
    try:
        with pytest.raises(ValueError):policy(project,tmp_path/'independent-output')
    finally:store.close()


def test_ordinary_text_writer_still_uses_legacy_output(tmp_path,monkeypatch):
    from ModuleFolders.Service.Cache.CacheFile import CacheFile
    from ModuleFolders.Service.Cache.CacheItem import CacheItem,TranslationStatus
    from ModuleFolders.Domain.FileOutputer import WriterUtil
    monkeypatch.setattr(WriterUtil,'get_ainiee_config',lambda:SimpleNamespace(keep_original_encoding=True))
    source=tmp_path/'text-source';source.mkdir();(source/'document.txt').write_text('source',encoding='utf-8')
    project=CacheProject(project_type='Txt');file=CacheFile(storage_path='document.txt',file_project_type='Txt')
    file.add_item(CacheItem(source_text='source',translated_text='translated',translation_status=TranslationStatus.TRANSLATED,extra={'line_break':0}))
    project.add_file(file);output=tmp_path/'text-output'
    FileOutputer().output_translated_content(project,output,source,{'translated_suffix':'.translated'})
    assert (output/'document.translated.txt').read_text(encoding='utf-8').strip()=='translated'
    assert (source/'document.txt').read_text(encoding='utf-8')=='source'


def test_hardlinked_file_is_not_an_output_directory(tmp_path):
    store,_,project,source=case(tmp_path);linked=tmp_path/'hardlinked-output'
    os.link(source/'keep.txt',linked)
    try:
        with pytest.raises(ValueError):policy(project,linked)
        assert linked.read_text(encoding='utf-8')=='source stays'
    finally:store.close()


@pytest.mark.skipif(os.name!='nt',reason='Windows junction proof')
def test_lexical_junction_is_refused_before_resolution(tmp_path):
    store,_,project,_=case(tmp_path);outside=tmp_path/'outside';outside.mkdir()
    junction=store.root/'exports'
    result=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)],capture_output=True)
    assert result.returncode==0,result.stderr
    try:
        with pytest.raises(ValueError):policy(project,junction/'new-output')
        assert not (outside/'new-output').exists()
    finally:store.close()


@pytest.mark.skipif(os.name!='nt',reason='Windows late junction proof')
def test_destination_is_rechecked_after_exchange_snapshot_before_write(tmp_path,monkeypatch):
    from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
    store,_,project,source=case(tmp_path);output=store.root/'AiNieeOutput'
    actual=GameProjectService.export_translations
    def swap(service):
        rows=actual(service)
        result=subprocess.run(['cmd','/c','mklink','/J',str(output),str(source)],capture_output=True)
        assert result.returncode==0,result.stderr
        return rows
    monkeypatch.setattr(GameProjectService,'export_translations',swap)
    try:
        with pytest.raises(ValueError):FileOutputer().output_translated_content(project,output,'unused',{})
        assert list(source.iterdir())==[source/'keep.txt']
    finally:store.close()


def executor_shell(project):
    module=importlib.import_module('ModuleFolders.Service.TaskExecutor.TaskExecutor')
    executor=object.__new__(module.TaskExecutor)
    executor.cache_manager=SimpleNamespace(project=project)
    executor.print=Mock();executor.info=Mock();executor.error=Mock();executor.emit=Mock()
    executor.file_writer=Mock()
    return module,executor


def test_manual_export_refuses_before_real_game_conversion_commits(tmp_path,monkeypatch):
    store,_,project,source=case(tmp_path);module,executor=executor_shell(project)
    converter=Mock();converter.convert.return_value='转换后文本'
    monkeypatch.setattr(module,'_create_opencc_converter',lambda *_:converter)
    executor.load_config=lambda:dict(response_conversion_toggle=True,opencc_preset='t2s',
        source_language='japanese',target_language='chinese_simplified')
    try:
        before=store.translation('u0');revision=store.metadata()['content_revision']
        executor.task_manual_export(0,{'export_path':str(source)})
        assert store.translation('u0')==before and store.metadata()['content_revision']==revision
        converter.convert.assert_not_called();executor.file_writer.output_translated_content.assert_not_called()
        executor.error.assert_called_once()
    finally:store.close()


def test_manual_export_aborts_if_current_project_switches_during_conversion(tmp_path):
    store,_,project,_=case(tmp_path);_,executor=executor_shell(project)
    other,_,foreign,_=case(tmp_path/'foreign')
    executor.load_config=lambda:dict(response_conversion_toggle=True,opencc_preset='t2s',
        source_language='japanese',target_language='chinese_simplified')
    def switch(*_,**__):executor.cache_manager.project=foreign;return True
    executor._convert_translated_text_with_opencc=switch
    try:
        executor.task_manual_export(0,{'export_path':str(store.root/'exports')})
        executor.file_writer.output_translated_content.assert_not_called()
        executor.error.assert_called_once()
    finally:store.close();other.close()


def test_real_conversion_remains_bound_to_original_database_during_project_switch(tmp_path,monkeypatch):
    store,_,project,_=case(tmp_path);module,executor=executor_shell(project)
    other,_,foreign,_=case(tmp_path/'foreign');foreign_before=other.translation('u0')
    executor.load_config=lambda:dict(response_conversion_toggle=True,opencc_preset='t2s',
        source_language='japanese',target_language='chinese_simplified')
    converter=Mock()
    def switch(text):executor.cache_manager.project=foreign;return '原工程的转换稿'
    converter.convert.side_effect=switch
    monkeypatch.setattr(module,'_create_opencc_converter',lambda *_:converter)
    try:
        executor.task_manual_export(0,{'export_path':str(store.root/'exports')})
        assert store.translation('u0')['text']=='原工程的转换稿'
        assert store.translation('u0')['origin']=='opencc'
        assert other.translation('u0')==foreign_before
        executor.file_writer.output_translated_content.assert_not_called()
        executor.error.assert_called_once()
    finally:store.close();other.close()


@pytest.mark.parametrize('mode',['translate','polish'])
def test_main_preflight_uses_correct_role_and_stops_before_filter_or_provider(tmp_path,mode):
    store,_,project,source=case(tmp_path);_,executor=executor_shell(project)
    project.stats_data=None
    executor.config=SimpleNamespace(initialize=lambda *_:None,prepare_for_active_platform=lambda *_:None,
        load_project_table_data=lambda *_:None,rpm_limit=60,
        label_output_path=str(source if mode=='translate' else tmp_path/'safe-translate'),
        label_polish_output_path=str(source if mode=='polish' else tmp_path/'safe-polish'))
    executor.request_limiter=Mock();executor.text_filter=Mock()
    executor.text_filter.filter_project.side_effect=RuntimeError('filter reached before preflight')
    try:
        with pytest.raises(ValueError):
            if mode=='translate':executor.translation_start_target(False)
            else:executor.polish_start_target(False)
        assert Base.work_status==Base.STATUS.TASKSTOPPED
        executor.request_limiter.set_limit.assert_not_called()
        executor.text_filter.filter_project.assert_not_called()
        assert store.jobs()==[]
    finally:store.close()
