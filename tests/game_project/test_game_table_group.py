"""Owner acceptance: a multi-file group is one captured parallel execution."""
import json,threading
from types import SimpleNamespace
from unittest.mock import Mock,patch
import importlib
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Domain.GameProject.Models import TranslationUnit,Occurrence,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
from test_game_task_reset import manager
from test_game_batch_preparation import config
from concurrent.futures import ThreadPoolExecutor
from test_game_event_admission import executor_for
from test_game_event_admission import page_for,immediate_thread
from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Service.Cache.CacheItem import TranslationStatus
_APP=None


def group(tmp_path):
    store=ProjectStore.create(tmp_path/'project',{'project_id':'table-group','engine':'rpgmaker-mz',
        'source_root':str(tmp_path/'source')})
    units=[TranslationUnit(f'u{i}','dialogue',f'来源{i}',scene_id=f's{i}',occurrences=(
        Occurrence(f'o{i}',f'data/Map00{i+1}.json',{'pointer':'/name'},hash_text(f'来源{i}')),)) for i in range(2)]
    store.replace_units(units);host=manager(build_projection(store))
    tasks=[{'file_path':f'data/Map00{i+1}.json','items_to_translate':[
        {'text_index':item.text_index} for item in host.project.get_file(f'data/Map00{i+1}.json').items]} for i in range(2)]
    return store,host,{'file_tasks':tasks,'update_event':987650,'done_event':987651}


def test_multifile_table_group_uses_parallel_real_jobs_with_one_scope(tmp_path,monkeypatch):
    from ModuleFolders.Service.SimpleExecutor.SimpleExecutor import SimpleExecutor
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,host,data=group(tmp_path);executor=SimpleExecutor(cache_manager=host);executor.emit=Mock()
    cfg=config();cfg.actual_thread_counts=2;barrier=threading.Barrier(2);calls=[]
    class Requester:
        def sent_request(self,messages,*_):
            targets=json.loads(messages[-1]['content']);calls.append(tuple(targets))
            barrier.wait(timeout=5)
            return False,'',json.dumps({uid:'译文'+uid for uid in targets}),1,1
    try:
        from ModuleFolders.Service.GameProject.GameBatchPreparation import GameBatchPreparation
        with patch('ModuleFolders.Service.GameProject.GameTableExecution.GameBatchPreparation',wraps=GameBatchPreparation) as prepared:
            result=executor._process_game_table(data,'translate',config=cfg,requester=Requester())
        assert prepared.call_count==1
        assert result=={'row_count':2,'error':''}
        coordinator=coordinator_for(host);scope=coordinator.current;jobs=store.jobs()
        assert len(jobs)==2 and coordinator.job_ids(scope)==tuple(sorted(job['job_id'] for job in jobs))
        assert all(job['payload']['game_execution_id']==scope.execution_id for job in jobs)
        assert coordinator.active_job_ids(scope)==() and not coordinator.active
        assert len([call for call in executor.emit.call_args_list if call.args[0]==Base.EVENT.TASK_STOP_DONE])==1
        assert all(store.translation(f'u{i}')['text']=='译文u'+str(i) for i in range(2))
    finally:executor._cleanup_event_subscriptions();store.close()


@pytest.mark.parametrize('page_module,page_name',[
    ('Table.BasicTablePage','BasicTablePage'),('Search.SearchResultPage','SearchResultPage'),
    ('Common.EditableIssueTablePage','EditableIssueTablePage')])
def test_actual_table_consumers_reject_an_old_execution_before_touching_cells(tmp_path,page_module,page_name):
    store,host,_=group(tmp_path);coordinator=coordinator_for(host)
    scope=coordinator.reserve(host.project,'table-translate');coordinator.accept(host.project,scope.payload())
    data={**scope.payload(),'game_execution_id':'previous-run','file_path':'data/Map001.json',
        'target_column_index':2,'updated_items':{0:'迟到文本'}}
    page=SimpleNamespace(cache_manager=host,_game_table_project=host.project,file_path=data['file_path'],
        COL_TRANS=2,table=Mock(),_sync_local_item=Mock())
    host.update_generated_translation=Mock(side_effect=AssertionError('stale cache update reached'))
    page.table.rowCount.side_effect=AssertionError('stale table reached')
    module=importlib.import_module('UserInterface.EditView.Proofreading.'+page_module)
    try:
        getattr(module,page_name)._on_table_update(page,123,data)
        host.update_generated_translation.assert_not_called();page.table.blockSignals.assert_not_called()
    finally:store.close()


def test_stop_cancels_queued_table_batches_and_waits_for_owned_inflight_job(tmp_path,monkeypatch):
    from ModuleFolders.Service.SimpleExecutor.SimpleExecutor import SimpleExecutor
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,host,data=group(tmp_path);executor=SimpleExecutor(cache_manager=host);executor.emit=Mock()
    module,controller=executor_for(host);entered=threading.Event();release=threading.Event();calls=[]
    cfg=config(actual_thread_counts=1)
    class Requester:
        def sent_request(self,messages,*_):
            targets=json.loads(messages[-1]['content']);calls.append(tuple(targets));entered.set()
            assert release.wait(5)
            return False,'',json.dumps({uid:'译文'+uid for uid in targets}),1,1
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(executor._process_game_table,data,'translate',cfg,Requester())
            try:
                assert entered.wait(5)
                scope=coordinator_for(host).current
                with patch.object(module,'LLMClientFactory'):controller.task_stop(Base.EVENT.TASK_STOP,scope.payload())
                assert coordinator_for(host).active and not future.done()
                assert not any(call.args[0]==Base.EVENT.TASK_STOP_DONE for call in executor.emit.call_args_list)
            finally:release.set()
            result=future.result(timeout=5)
        assert result['row_count']==0 and result['error']
        assert len(calls)==len(store.jobs())==1 and store.jobs()[0]['run_state']=='CANCELLED'
        assert all(store.translation(f'u{i}') is None for i in range(2))
        assert not coordinator_for(host).active and coordinator_for(host).active_job_ids(scope)==()
        assert sum(call.args[0]==Base.EVENT.TASK_STOP_DONE for call in executor.emit.call_args_list)==1
    finally:release.set();executor._cleanup_event_subscriptions();store.close()


@pytest.mark.parametrize('empty_message',[False,True])
def test_table_partial_failure_is_reported_and_keeps_other_accepted_rows(tmp_path,monkeypatch,empty_message):
    from ModuleFolders.Service.SimpleExecutor.SimpleExecutor import SimpleExecutor
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,host,data=group(tmp_path);executor=SimpleExecutor(cache_manager=host);executor.emit=Mock()
    class Requester:
        def sent_request(self,messages,*_):
            targets=json.loads(messages[-1]['content'])
            if 'u1' in targets:
                if empty_message:raise RuntimeError()
                return False,'','invalid json',1,1
            return False,'',json.dumps({uid:'译文'+uid for uid in targets}),1,1
    try:
        result=executor._process_game_table(data,'translate',config(actual_thread_counts=2),Requester())
        assert result['row_count']==1 and result['error']
        assert store.translation('u0')['text']=='译文u0' and store.translation('u1') is None
        assert sorted(job['run_state'] for job in store.jobs())==['COMPLETED']+['FAILED']*(1 if empty_message else 3)
        done=[call.args[1] for call in executor.emit.call_args_list if call.args[0]==data['done_event']]
        assert all(packet['status']=='error' for packet in done)
    finally:executor._cleanup_event_subscriptions();store.close()


@pytest.mark.parametrize('damage',['missing','execution','dataset','project','root'])
def test_queued_table_start_rejects_foreign_events_before_any_thread(tmp_path,damage):
    from ModuleFolders.Service.SimpleExecutor.SimpleExecutor import SimpleExecutor
    module=importlib.import_module('ModuleFolders.Service.SimpleExecutor.SimpleExecutor')
    store,host,data=group(tmp_path);executor=SimpleExecutor(cache_manager=host);executor.emit=Mock()
    coordinator=coordinator_for(host);scope=coordinator.reserve(host.project,'table-translate')
    packet={**data,**scope.payload()}
    if damage=='missing':packet=data
    elif damage=='execution':packet['game_execution_id']='previous'
    elif damage=='dataset':packet['dataset_revision']+=1
    elif damage=='project':packet['project_id']='foreign'
    else:packet['game_project_root']='foreign-root'
    try:
        with patch.object(module.threading,'Thread') as thread:executor.handle_table_translation_start(800,packet)
        thread.assert_not_called();executor.emit.assert_not_called()
        assert coordinator.active and coordinator.current is scope and store.jobs()==[]
    finally:executor._cleanup_event_subscriptions();store.close()


@pytest.mark.parametrize('kind',['main','table'])
def test_stop_between_reservation_and_queued_start_releases_own_ui_without_provider(tmp_path,monkeypatch,kind):
    from ModuleFolders.Service.SimpleExecutor.SimpleExecutor import SimpleExecutor
    from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,host,data=group(tmp_path);coordinator=coordinator_for(host);bar=page_for(host)
    scope=coordinator.reserve_current(host,'translate' if kind=='main' else 'table-translate',ui_owned=True)
    coordinator.stop_current()
    try:
        if kind=='main':
            module,executor=executor_for(host)
            executor.translation_start_target=module.TaskExecutor.translation_start_target.__get__(executor)
            with patch.object(module.threading,'Thread',side_effect=immediate_thread),patch.object(module.TaskConfig,'initialize') as initialize:
                executor.task_start(Base.EVENT.TASK_START,{**scope.payload(),'current_mode':TaskType.TRANSLATION,'continue_status':False})
        else:
            module=importlib.import_module('ModuleFolders.Service.SimpleExecutor.SimpleExecutor')
            executor=SimpleExecutor(cache_manager=host);executor.emit=Mock()
            with patch.object(module.threading,'Thread') as thread,patch.object(module.TaskConfig,'initialize') as initialize:
                executor.handle_table_translation_start(Base.EVENT.TABLE_TRANSLATE_START,{**data,**scope.payload()})
            thread.assert_not_called()
        initialize.assert_not_called();assert store.jobs()==[] and not coordinator.active
        done=[call.args for call in executor.emit.call_args_list if call.args[0]==Base.EVENT.TASK_STOP_DONE]
        assert len(done)==1
        bar.task_stop_done(*done[0]);assert Base.work_status==Base.STATUS.IDLE
        with pytest.raises(ValueError,match='START_CONTEXT_INVALID'):coordinator.accept(host.project,scope.payload())
    finally:
        if kind=='table':executor._cleanup_event_subscriptions()
        store.close()


def test_table_start_enables_shared_stop_controls_and_own_done_releases_them(tmp_path,monkeypatch):
    from UserInterface.EditView.Translation.BottomCommandBar import BottomCommandBar
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TABLE_TASK)
    store,host,_=group(tmp_path);coordinator=coordinator_for(host);bar=page_for(host)
    scope=coordinator.reserve_current(host,'table-translate',ui_owned=True)
    try:
        BottomCommandBar._table_task_started(bar,800,{**scope.payload(),'game_execution_id':'old'})
        bar.start_btn.setEnabled.assert_not_called()
        BottomCommandBar._table_task_started(bar,800,scope.payload())
        bar.start_btn.setEnabled.assert_called_once_with(False);bar.ui_update_timer.start.assert_called_once()
        coordinator.finish(scope);bar.task_stop_done(Base.EVENT.TASK_STOP_DONE,scope.payload())
        assert Base.work_status==Base.STATUS.IDLE
    finally:store.close()


@pytest.mark.parametrize('kind',['basic','search','issue'])
def test_actual_qt_table_producer_and_consumer_share_a_bound_execution(tmp_path,monkeypatch,kind):
    global _APP
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
    configure_qt_paths()
    from PyQt5.QtWidgets import QApplication
    _APP=QApplication.instance() or QApplication([]);app=_APP
    from UserInterface.EditView.Proofreading.Table.BasicTablePage import BasicTablePage
    from UserInterface.EditView.Proofreading.Search.SearchResultPage import SearchResultPage
    from UserInterface.EditView.Proofreading.Common.EditableIssueTablePage import EditableIssueTablePage
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,host,_=group(tmp_path);items=list(host.project.items_iter());path='data/Map001.json'
    if kind=='basic':page=BasicTablePage(path,[items[0]],host)
    elif kind=='search':page=SearchResultPage([(item.get_extra('game_storage_path'),i,item) for i,item in enumerate(items)],host,{})
    else:page=EditableIssueTablePage([{'file_path':item.get_extra('game_storage_path'),'text_index':item.text_index,
        'target_field':'translated_text','source':item.source_text,'check_text':''} for item in items],host,
        update_event=987650,done_event=987651)
    page.emit=Mock();page.info_toast=Mock();page.warning_toast=Mock();page.success_toast=Mock()
    try:
        page.table.selectAll()
        (page._translate_selected_rows if kind=='issue' else page._translate_text)()
        event,packet=page.emit.call_args.args;coordinator=coordinator_for(host);scope=coordinator.current
        assert event==Base.EVENT.TABLE_TRANSLATE_START and Base.work_status==Base.STATUS.TABLE_TASK
        assert scope.ui_owned and len(packet['file_tasks'])==(1 if kind=='basic' else 2)
        assert 'source_text' not in packet['file_tasks'][0]['items_to_translate'][0]
        coordinator.accept(host.project,packet)
        store.commit(TranslationProposal('u0','规范接受文本',store.unit('u0').source_hash,origin='manual'))
        update={**scope.payload(),'file_path':path,'target_column_index':2,'translation_status':TranslationStatus.TRANSLATED,
            'updated_items':{items[0].text_index:'规范接受文本'}}
        page._on_table_update(123,{**update,'game_execution_id':'previous'})
        assert page.table.item(0,page.COL_TRANS).text()==''
        page._on_table_update(123,update)
        assert page.table.item(0,page.COL_TRANS).text()=='规范接受文本'
        done={**scope.payload(),'file_path':path,'operation':'translate','status':'success','updated_item_count':1}
        page.isVisible=Mock(return_value=True)
        page._on_task_done(123,{**done,'game_execution_id':'previous'})
        page.success_toast.assert_not_called()
        page._on_task_done(123,done);page.success_toast.assert_called_once()
        old_project=host.project;host.project=build_projection(store)
        page._on_table_update(123,{**update,'updated_items':{items[0].text_index:'伪造'}})
        assert page.table.item(0,page.COL_TRANS).text()=='规范接受文本'
        host.project=old_project
    finally:page._cleanup_event_subscriptions();page.close();app.processEvents();store.close()
