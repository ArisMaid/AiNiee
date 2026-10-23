"""Damaged game identity must never select ordinary edit/reset/request paths."""
from types import SimpleNamespace
from unittest.mock import Mock,patch
import importlib
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
from ModuleFolders.Service.GameProject.CacheBridge import refresh_projection,sync_generated_cache
from ModuleFolders.Service.Cache.CacheItem import CacheItem,TranslationStatus
from ModuleFolders.Service.Cache.CacheProject import CacheProject
from ModuleFolders.Service.Cache.CacheFile import CacheFile
from test_game_task_reset import seed,by_id,authority,manager
from test_game_context_entrypoints import task_config


def damage(project,kind):
    item=by_id(project)['u0']
    if kind=='project_root':project.extra.pop('game_project_root')
    elif kind=='item_root':item.extra.pop('game_project_root')
    elif kind=='foreign_item':item.set_extra('game_project_root','foreign-root')
    elif kind=='project_id':project.project_id='wrong-project'
    elif kind=='root_empty':project.set_extra('game_project_root','')
    else:raise AssertionError(kind)


@pytest.mark.parametrize('kind',['project_root','item_root','foreign_item','project_id','root_empty'])
@pytest.mark.parametrize('operation',['edit','reset','refresh'])
def test_damaged_identity_rejects_edits_resets_and_reload_before_fallback(tmp_path,kind,operation):
    store,_,host=seed(tmp_path);damage(host.project,kind)
    before=authority(store);item=by_id(host.project)['u0'];text=item.translated_text
    try:
        with pytest.raises(ValueError):
            if operation=='edit':host.update_item_text('data/Map001.json',item.text_index,'translated_text','untrusted')
            elif operation=='reset':host.reset_project_status(TaskType.TRANSLATION)
            else:refresh_projection(host.project)
        assert authority(store)==before and item.translated_text==text
        host.save_to_file.assert_not_called()
    finally:store.close()


@pytest.mark.parametrize('kind',['project_root','item_root','foreign_item','project_id','root_empty'])
def test_invalid_generated_notification_returns_false_without_view_or_sql_mutation(tmp_path,kind):
    store,_,host=seed(tmp_path);damage(host.project,kind);host.warning=Mock()
    before=authority(store);item=by_id(host.project)['u0'];text=item.translated_text
    try:
        assert host.update_generated_translation('data/Map001.json',item.text_index,text,TranslationStatus.TRANSLATED) is False
        assert authority(store)==before and item.translated_text==text
    finally:store.close()


@pytest.mark.parametrize('mode',['translate','polish'])
@pytest.mark.parametrize('kind',['missing','empty','unhashable'])
def test_direct_tasks_with_explicit_game_markers_refuse_all_missing_roots(tmp_path,mode,kind):
    store,_,host=seed(tmp_path);items=list(host.project.items_iter())
    try:
        for item in items:
            if kind=='missing':item.extra.pop('game_project_root')
            elif kind=='empty':item.set_extra('game_project_root','')
            else:item.set_extra('game_project_root',[])
        if mode=='translate':
            from ModuleFolders.Service.TaskExecutor.TranslatorTask import TranslatorTask
            task=TranslatorTask(task_config(),None,'ja')
        else:
            from ModuleFolders.Service.TaskExecutor.PolisherTask import PolisherTask
            task=PolisherTask(task_config(),None)
        task.set_items(items);task.set_previous_items([])
        with patch.object(task.text_processor,'replace_all',side_effect=AssertionError('ordinary path reached')):
            with pytest.raises(ValueError,match='GAME.*PROJECT|PROJECT.*IDENTITY'):
                if mode=='translate':task.prepare('owner-test')
                else:task.prepare()
        assert store.jobs()==[]
    finally:store.close()


@pytest.mark.parametrize('mode',['translate','polish'])
@pytest.mark.parametrize('kind',['project_root','item_root','foreign_item','project_id','root_empty'])
def test_public_table_operation_rejects_before_configuration_or_request(tmp_path,mode,kind):
    from ModuleFolders.Service.SimpleExecutor.SimpleExecutor import SimpleExecutor
    store,_,host=seed(tmp_path);damage(host.project,kind)
    executor=SimpleExecutor(cache_manager=host);executor.emit=Mock()
    data={'file_path':'data/Map001.json','items_to_translate':[{'text_index':0}],
        'items_to_polish':[{'text_index':0}],'done_event':987654}
    config_module=importlib.import_module('ModuleFolders.Service.SimpleExecutor.SimpleExecutor')
    try:
        before=authority(store)
        with patch.object(config_module.TaskConfig,'initialize',side_effect=AssertionError('config reached')) as initialized:
            if mode=='translate':result=executor.process_table_translation(data)
            else:result=executor.process_table_polish(data)
        initialized.assert_not_called()
        assert result['row_count']==0 and result['error']
        assert authority(store)==before and store.jobs()==[]
        events=[data for event,data in (call.args for call in executor.emit.call_args_list) if event==987654]
        assert events and events[-1]['status']=='error'
    finally:executor._cleanup_event_subscriptions();store.close()


def test_ordinary_edit_does_not_iterate_the_whole_project(tmp_path):
    project=CacheProject(project_type='Txt');file=CacheFile(storage_path='doc.txt')
    item=CacheItem(source_text='source',translated_text='old',translation_status=TranslationStatus.TRANSLATED)
    file.add_item(item);project.add_file(file);host=manager(project)
    with patch.object(project,'items_iter',side_effect=AssertionError('whole-project scan on edit')):
        host.update_item_text('doc.txt',0,'translated_text','new')
        host.update_generated_translation('doc.txt',0,'generated',TranslationStatus.POLISHED)
    assert item.translated_text=='generated' and item.translation_status==TranslationStatus.POLISHED


def test_stale_status_notification_cannot_undo_a_persisted_reset(tmp_path):
    store,_,host=seed(tmp_path)
    try:
        assert host.reset_project_status(TaskType.TRANSLATION)==2
        item=by_id(host.project)['u0'];text=item.translated_text;before=authority(store)
        assert host.update_generated_translation('data/Map001.json',item.text_index,text,TranslationStatus.TRANSLATED) is False
        assert item.translation_status==TranslationStatus.UNTRANSLATED and authority(store)==before
    finally:store.close()


@pytest.mark.parametrize('kind',['project_root','foreign_item'])
def test_real_edit_slot_restores_text_and_reports_identity_error(tmp_path,kind):
    from ModuleFolders.Service.GameProject.CacheBridge import apply_table_edit
    store,_,host=seed(tmp_path);damage(host.project,kind)
    item=by_id(host.project)['u0'];prior=item.translated_text
    table=SimpleNamespace(signalsBlocked=lambda:False,blockSignals=Mock())
    page=SimpleNamespace(cache_manager=host,table=table,warning_toast=Mock());cell=Mock()
    try:
        before=authority(store)
        assert apply_table_edit(page,cell,'data/Map001.json',item.text_index,'translated_text','untrusted') is False
        cell.setText.assert_called_once_with(prior);page.warning_toast.assert_called_once()
        assert authority(store)==before and item.translated_text==prior
    finally:store.close()


def test_generated_refresh_preserves_unknown_control_exclusion(tmp_path):
    from dataclasses import replace
    from ModuleFolders.Service.GameProject.CacheBridge import build_projection
    store,units,host=seed(tmp_path)
    try:
        blocked=replace(units[0],source_text='source'+chr(92)+'Unknown[1]',source_hash='')
        store.replace_units([blocked,*units[1:]]);host.project=build_projection(store)
        item=by_id(host.project)['u0'];before=authority(store)
        assert item.translation_status==TranslationStatus.EXCLUDED
        assert host.update_generated_translation('data/Map001.json',item.text_index,'',TranslationStatus.EXCLUDED) is True
        assert item.translation_status==TranslationStatus.EXCLUDED
        assert item.get_extra('blocked_token_codes') and authority(store)==before
    finally:store.close()


@pytest.mark.parametrize('unit_id,status',[('u1',TranslationStatus.POLISHED),('u2',TranslationStatus.EXCLUDED)])
def test_stale_status_notice_does_not_downgrade_polished_or_locked_cache(tmp_path,unit_id,status):
    store,_,host=seed(tmp_path)
    try:
        item=by_id(host.project)[unit_id];before=authority(store)
        assert host.update_generated_translation('data/Map001.json',item.text_index,item.translated_text,TranslationStatus.TRANSLATED) is False
        assert item.translation_status==status and authority(store)==before
    finally:store.close()


@pytest.mark.parametrize('index',[False,'0',-1])
def test_game_edit_rejects_noncanonical_index_before_acceptance(tmp_path,index):
    store,_,host=seed(tmp_path)
    try:
        before=authority(store)
        with pytest.raises(ValueError):host.update_item_text('data/Map001.json',index,'translated_text','bad')
        assert authority(store)==before
    finally:store.close()


def test_single_game_edit_and_notice_do_not_rescan_the_canonical_graph(tmp_path):
    from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
    store,_,host=seed(tmp_path)
    try:
        item=by_id(host.project)['u0']
        with patch.object(ProjectStore,'units',side_effect=AssertionError('whole-project scan on single edit')):
            host.update_item_text('data/Map001.json',item.text_index,'translated_text','人工更新')
            assert host.update_generated_translation('data/Map001.json',item.text_index,'人工更新',TranslationStatus.TRANSLATED)
        assert store.translation('u0')['text']=='人工更新'
    finally:store.close()


def test_older_source_cache_cannot_display_new_source_acceptance(tmp_path):
    from dataclasses import replace
    from ModuleFolders.Domain.GameProject.Models import TranslationProposal
    from ModuleFolders.Service.GameProject.CacheBridge import update_cached_item
    store,units,host=seed(tmp_path)
    try:
        item=by_id(host.project)['u0'];old_source=item.source_text
        new_unit=replace(units[0],source_text='新的来源',source_hash='')
        store.replace_units([new_unit,*units[1:]])
        current=store.unit('u0');revision=store.translation('u0')['revision']
        store.commit(TranslationProposal('u0','新来源接受译文',current.source_hash,revision,origin='manual'))
        before=authority(store)
        assert host.update_generated_translation('data/Map001.json',item.text_index,'新来源接受译文',TranslationStatus.TRANSLATED) is False
        update_cached_item(item,store)
        assert item.source_text==old_source and item.translated_text==''
        assert item.translation_status==TranslationStatus.UNTRANSLATED and authority(store)==before
    finally:store.close()


def test_real_table_polish_notification_preserves_canonical_polish_status(tmp_path,monkeypatch):
    from ModuleFolders.Service.SimpleExecutor.SimpleExecutor import SimpleExecutor
    from UserInterface.EditView.Proofreading.Table.BasicTablePage import BasicTablePage
    from test_game_batch_preparation import Requester
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,host=seed(tmp_path);executor=SimpleExecutor(cache_manager=host);executor.emit=Mock()
    try:
        target=by_id(host.project)['u0']
        result=executor._process_game_table({'file_path':'data/Map001.json',
            'items_to_polish':[{'text_index':target.text_index}]},'polish',task_config(),Requester())
        assert result=={'row_count':1,'error':''}
        event,payload=next(call.args for call in executor.emit.call_args_list if call.args[0]==Base.EVENT.TABLE_BASIC_UPDATE)
        assert payload['translation_status']==TranslationStatus.POLISHED
        assert payload['game_project_root']==str(store.root) and payload['project_id']==host.project.project_id
        page=SimpleNamespace(file_path='data/Map001.json',COL_TRANS=2,COL_NUM=0,
            cache_manager=host,_game_table_project=host.project,_items_by_text_index={target.text_index:target},
            table=SimpleNamespace(rowCount=lambda:0,scheduleResizeRowsToContents=Mock()),
            _item_changed_handler_enabled=True)
        page._sync_local_item=Mock(side_effect=lambda *args:BasicTablePage._sync_local_item(page,*args))
        before=authority(store)
        BasicTablePage._on_table_update(page,event,payload)
        page._sync_local_item.assert_called_once()
        assert target.translation_status==TranslationStatus.POLISHED
        assert target.translated_text==store.translation('u0')['text'] and authority(store)==before
    finally:executor._cleanup_event_subscriptions();store.close()
