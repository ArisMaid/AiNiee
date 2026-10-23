"""Native proofreading must use canonical text and scoped accepted proposals."""
import json,threading
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
from ModuleFolders.Service.Cache.CacheItem import TranslationStatus
from test_game_table_group import group
from test_game_event_admission import executor_for
from test_game_batch_preparation import config
from test_game_batch_preparation import create,Requester
from test_game_task_reset import manager
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from concurrent.futures import ThreadPoolExecutor
_APP=None


def proof_data(data):
    return {'proofread_jobs':[{'file_path':task['file_path'],'items_to_proofread':[
        {**row,'source_text':'伪造原文','translation_text':'伪造译文','error_type':'术语错误'}
        for row in task['items_to_translate']]} for task in data['file_tasks']],
        'update_event':987650,'done_event':987651}


def test_direct_game_proofread_reads_canonical_text_and_persists_polish_jobs(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,host,data=group(tmp_path);module,executor=executor_for(host)
    store.commit(TranslationProposal('u0','规范译文',store.unit('u0').source_hash,origin='manual'))
    cfg=config(actual_thread_counts=2);cfg.get_active_platform_configuration=Mock(return_value={})
    calls=[]
    class Requester:
        def sent_request(self,messages,prompt,*_):
            payload=json.loads(messages[-1]['content']);calls.append(payload)
            assert len(payload)==1 and '伪造' not in json.dumps(messages,ensure_ascii=False)
            return False,'',json.dumps({uid:'修正'+(value['current_translation'] or value['text']) for uid,value in payload.items()}),1,1
    try:
        result=executor.table_proofread_start_target(proof_data(data),config=cfg,requester=Requester())
        assert result=={'row_count':2,'error':''} and len(calls)==2
        scope=coordinator_for(host).current
        assert scope.operation=='table-proofread' and not coordinator_for(host).active
        assert store.translation('u0')['text']=='修正规范译文'
        assert store.translation('u1')['text']=='修正来源1'
        assert all(job['operation']=='POLISH' and job['payload']['request_mode']=='proofread'
            and job['payload']['game_execution_id']==scope.execution_id and job['run_state']=='COMPLETED' for job in store.jobs())
        assert all(call.args==('proofread',) for call in cfg.get_active_platform_configuration.call_args_list)
        done=[call.args[1] for call in executor.emit.call_args_list if call.args[0]==987651]
        assert len(done)==1 and done[0]['operation']=='proofread' and done[0]['updated_file_count']==2
        assert done[0]['updated_item_count']==2
    finally:store.close()


def test_queued_game_proofread_without_scope_cannot_start_legacy_worker(tmp_path):
    store,host,data=group(tmp_path);module,executor=executor_for(host)
    executor._executor_lock=threading.Lock();executor._active_executor=None
    try:
        with patch.object(module.threading,'Thread') as thread,patch.object(module,'ProofreadTask') as legacy:
            executor.table_proofread_start(Base.EVENT.TABLE_PROOFREAD_START,proof_data(data))
        thread.assert_not_called();legacy.assert_not_called();assert store.jobs()==[]
    finally:store.close()


@pytest.mark.parametrize('failure',['missing-id','duplicate-id','token','empty','none','transport'])
def test_proofread_retries_once_with_fixed_markers_and_accounts_for_real_attempts(tmp_path,monkeypatch,failure):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,units,_=create(tmp_path,texts=[r'\V[1]原文'])
    store.commit(TranslationProposal('u0',r'\V[1]已接受',units[0].source_hash,origin='manual'))
    host=manager(build_projection(store));_,executor=executor_for(host);calls=[]
    cfg=config(actual_thread_counts=1);cfg.get_active_platform_configuration=lambda *_:{}
    class Local:
        def sent_request(self,messages,*_):
            payload=json.loads(messages[-1]['content']);calls.append(payload)
            value=payload['u0'];assert value['current_translation'].endswith('已接受')
            if len(calls)==1:
                raw={'missing-id':'{}','duplicate-id':'{"u0":"a","u0":"b"}',
                    'token':json.dumps({'u0':'缺标记'}),'empty':'','none':None,'transport':'ignored'}[failure]
                return failure=='transport','',raw,2,3
            return False,'',json.dumps({'u0':'修正'+value['current_translation']}),2,3
    try:
        result=executor.table_proofread_start_target({'file_path':'data/Map001.json',
            'items_to_proofread':[{'text_index':0}]},config=cfg,requester=Local())
        assert result=={'row_count':1,'error':''} and len(calls)==2
        assert calls[0]==calls[1]  # new jobs never recapture a newer CAS snapshot
        assert store.translation('u0')['text']==r'修正\V[1]已接受'
        assert store.translation('u0')['origin']=='polish'
        assert [job['run_state'] for job in store.jobs()].count('COMPLETED')==1
        assert len(store.jobs())==2
        snapshots=[call.args[1] for call in executor.emit.call_args_list if call.args[0]==Base.EVENT.TASK_UPDATE]
        assert snapshots[-1]['total_requests']==2 and snapshots[-1]['error_requests']==1
        assert snapshots[-1]['token']==10
        assert snapshots[-1]['game_progress_revision']==2
    finally:store.close()


@pytest.mark.parametrize('change',['edit','lock','dataset'])
def test_proofread_conflicts_do_not_retry_or_overwrite_new_canonical_state(tmp_path,monkeypatch,change):
    from dataclasses import replace
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,units,_=create(tmp_path,texts=['原文']);host=manager(build_projection(store));_,executor=executor_for(host)
    calls=[];expected=[];cfg=config(actual_thread_counts=1);cfg.get_active_platform_configuration=lambda *_:{}
    class Local:
        def sent_request(self,messages,*_):
            calls.append(1)
            if change=='edit':store.commit(TranslationProposal('u0','后来的人工译文',units[0].source_hash,origin='manual'))
            elif change=='lock':store.set_locked('u0',True)
            else:store.replace_units([replace(units[0],scene_id='changed')])
            expected.append(store.translation('u0'))
            return False,'',json.dumps({'u0':'旧响应'}),1,1
    try:
        result=executor.table_proofread_start_target({'file_path':'data/Map001.json',
            'items_to_proofread':[{'text_index':0}]},config=cfg,requester=Local())
        assert result['row_count']==0 and result['error'] and len(calls)==1
        assert store.translation('u0')==expected[0] and len(store.jobs())==1
    finally:store.close()


def test_repeated_invalid_proofread_stops_after_three_jobs_and_keeps_old_text(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,host,data=group(tmp_path);_,executor=executor_for(host);packet=proof_data(data)
    packet['proofread_jobs']=packet['proofread_jobs'][:1]
    store.commit(TranslationProposal('u0','原有接受文本',store.unit('u0').source_hash,origin='manual'))
    before=store.translation('u0');calls=[];cfg=config(actual_thread_counts=1)
    cfg.get_active_platform_configuration=lambda *_:{}
    class Local:
        def sent_request(self,*_):calls.append(1);return False,'','not json',1,1
    try:
        result=executor.table_proofread_start_target(packet,config=cfg,requester=Local())
        assert result['row_count']==0 and result['error']
        assert len(calls)==len(store.jobs())==3 and store.translation('u0')==before
        assert all(job['run_state']=='FAILED' for job in store.jobs())
    finally:store.close()


def test_stopping_proofread_cancels_queue_and_waits_for_its_late_response(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,host,data=group(tmp_path);module,executor=executor_for(host);entered=threading.Event();release=threading.Event()
    calls=[];queued=threading.Event();submissions=[]
    real_submit=ThreadPoolExecutor.submit
    def observed_submit(pool,*args,**kwargs):
        future=real_submit(pool,*args,**kwargs)
        if pool._thread_name_prefix=='translator-table':
            submissions.append(future)
            if len(submissions)==2:queued.set()
        return future
    monkeypatch.setattr(ThreadPoolExecutor,'submit',observed_submit)
    cfg=config(actual_thread_counts=1);cfg.get_active_platform_configuration=lambda *_:{}
    class Local:
        def sent_request(self,messages,*_):
            calls.append(1);entered.set();assert release.wait(5)
            return False,'',json.dumps({uid:'迟到文本' for uid in json.loads(messages[-1]['content'])}),1,1
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(executor.table_proofread_start_target,proof_data(data),config=cfg,requester=Local())
            try:
                assert entered.wait(5) and queued.wait(5);scope=coordinator_for(host).current
                with patch.object(module,'LLMClientFactory'):executor.task_stop(Base.EVENT.TASK_STOP,scope.payload())
                assert not future.done() and coordinator_for(host).active
            finally:release.set()
            result=future.result(timeout=5)
        assert result['row_count']==0 and result['error']
        assert len(calls)==len(store.jobs())==1 and store.jobs()[0]['run_state']=='CANCELLED'
        assert all(store.translation(f'u{i}') is None for i in range(2))
        assert not coordinator_for(host).active and coordinator_for(host).active_job_ids(scope)==()
        snapshots=[call.args[1] for call in executor.emit.call_args_list if call.args[0]==Base.EVENT.TASK_UPDATE]
        assert snapshots[-1]['total_requests']==1
    finally:release.set();store.close()


def test_prelocked_proofread_is_empty_without_model_or_new_jobs(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,host,data=group(tmp_path);_,executor=executor_for(host);packet=proof_data(data)
    packet['proofread_jobs']=packet['proofread_jobs'][:1];store.set_locked('u0',True)
    before=store.translation('u0');requester=Mock();cfg=config(actual_thread_counts=2)
    try:
        result=executor.table_proofread_start_target(packet,config=cfg,requester=requester)
        assert result=={'row_count':0,'error':''} and store.jobs()==[]
        requester.sent_request.assert_not_called();assert store.translation('u0')==before
    finally:store.close()


@pytest.mark.parametrize('field',['translated_text','source_text'])
def test_real_qt_proofread_producer_reserves_before_queue_and_limits_source_fields(tmp_path,monkeypatch,field):
    global _APP
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_paths
    configure_qt_paths()
    from PyQt5.QtWidgets import QApplication
    _APP=QApplication.instance() or QApplication([])
    from UserInterface.EditView.Proofreading.Common.EditableIssueTablePage import EditableIssueTablePage
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,host,data=group(tmp_path);items=list(host.project.items_iter())
    rows=[{'file_path':item.get_extra('game_storage_path'),'text_index':item.text_index,'target_field':field,
        'source':'伪造原文','check_text':'伪造译文','error_type':'校对提示'} for item in items]
    page=EditableIssueTablePage(rows,host,update_event=987650,done_event=987651)
    page.emit=Mock();page.info_toast=Mock();page.warning_toast=Mock()
    try:
        page._proofread_all_rows()
        if field=='source_text':
            page.emit.assert_not_called();assert Base.work_status==Base.STATUS.IDLE
            page.warning_toast.assert_called_once()
        else:
            event,packet=page.emit.call_args.args;scope=coordinator_for(host).current
            assert event==Base.EVENT.TABLE_PROOFREAD_START and scope.operation=='table-proofread'
            assert scope.ui_owned and Base.work_status==Base.STATUS.TABLE_TASK and store.jobs()==[]
            assert '伪造' not in json.dumps(packet,ensure_ascii=False) and len(packet['file_tasks'])==2
            page._proofread_all_rows();assert page.emit.call_count==1
    finally:page._cleanup_event_subscriptions();page.close();_APP.processEvents();store.close()


def test_ordinary_proofread_still_uses_legacy_worker_and_scoped_packets_cannot_enter_it(tmp_path):
    from ModuleFolders.Service.TaskExecutor.ProofreadTask import ProofreadTask
    from ModuleFolders.Service.Cache.CacheProject import CacheProject
    module,executor=executor_for(SimpleNamespace(project=CacheProject(project_type='Txt')))
    with patch.object(module,'ProofreadTask') as legacy:
        executor.table_proofread_start_target({'proofread_jobs':[]})
        legacy.return_value.run.assert_called_once()
    with pytest.raises(ValueError,match='REQUIRES_NATIVE'):
        ProofreadTask({'game_execution_id':'game'},Mock(),Mock())


def test_retry_never_recaptures_a_human_revision_after_the_first_invalid_response(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    store,units,_=create(tmp_path,texts=['原文']);host=manager(build_projection(store));_,executor=executor_for(host)
    calls=[];saved=[];cfg=config(actual_thread_counts=1);cfg.get_active_platform_configuration=lambda *_:{}
    class Local:
        def sent_request(self,messages,*_):
            calls.append(1)
            if len(calls)==1:
                store.commit(TranslationProposal('u0','新人工文本',units[0].source_hash,origin='manual'))
                saved.append(store.translation('u0'));return False,'','bad json',1,1
            return False,'',json.dumps({'u0':'旧快照的重试'}),1,1
    try:
        result=executor.table_proofread_start_target({'file_path':'data/Map001.json',
            'items_to_proofread':[{'text_index':0}]},config=cfg,requester=Local())
        assert result['row_count']==0 and result['error'] and len(calls)==2
        assert store.translation('u0')==saved[0]
        assert len(store.jobs())==2 and all(job['run_state']=='FAILED' for job in store.jobs())
    finally:store.close()


@pytest.mark.parametrize('damage',['project_root','item_root','foreign_item','project_id','root_empty'])
def test_damaged_game_proofread_refuses_before_provider_configuration(tmp_path,damage):
    from test_game_task_reset import seed,authority
    from test_game_cache_identity import damage as damage_view
    store,_,host=seed(tmp_path);module,executor=executor_for(host)
    damage_view(host.project,damage);before=authority(store)
    try:
        with patch.object(module.TaskConfig,'initialize',side_effect=AssertionError('config reached')) as initialized:
            result=executor.table_proofread_start_target({'file_path':'data/Map001.json',
                'items_to_proofread':[{'text_index':0}]})
        initialized.assert_not_called();assert result['error'] and result['row_count']==0
        assert store.jobs()==[] and authority(store)==before
    finally:store.close()


@pytest.mark.parametrize('stopping',[False,True])
def test_queued_proofread_consumes_only_own_reservation_and_finishes_once(tmp_path,monkeypatch,stopping):
    from test_game_event_admission import page_for
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TABLE_TASK)
    store,host,data=group(tmp_path);module,executor=executor_for(host);coordinator=coordinator_for(host)
    scope=coordinator.reserve_current(host,'table-proofread',ui_owned=True)
    packet={**scope.payload(),**proof_data(data)};bar=page_for(host)
    if stopping:coordinator.stop_current()
    cfg=config(actual_thread_counts=2);cfg.get_active_platform_configuration=lambda *_:{}
    class Local:
        def sent_request(self,messages,*_):
            return False,'',json.dumps({uid:'正确文本' for uid in json.loads(messages[-1]['content'])}),1,1
    actual=executor.table_proofread_start_target
    executor.table_proofread_start_target=lambda data,task_scope=None:actual(data,task_scope=task_scope,config=cfg,requester=Local())
    try:
        with patch.object(module.threading,'Thread') as thread:
            executor.table_proofread_start(Base.EVENT.TABLE_PROOFREAD_START,packet)
            first=thread.call_count
            executor.table_proofread_start(Base.EVENT.TABLE_PROOFREAD_START,packet)
            assert thread.call_count==first==int(not stopping)
            launch=thread.call_args.kwargs if not stopping else None
        # Restore the real Thread before running code which creates a pool.
        if launch:launch['target'](*launch.get('args',()),**launch.get('kwargs',{}))
        done=[call.args for call in executor.emit.call_args_list if call.args[0]==Base.EVENT.TASK_STOP_DONE]
        assert len(done)==1 and not coordinator.active and len(store.jobs())==int(not stopping)*2
        bar.task_stop_done(*done[0]);assert Base.work_status==Base.STATUS.IDLE
    finally:store.close()
