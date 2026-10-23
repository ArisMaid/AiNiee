"""Owner checks through the actual task and table preparation entrypoints."""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from ModuleFolders.Base.Base import Base
from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.Cache.CacheManager import CacheManager
from ModuleFolders.Service.Cache.CacheItem import CacheItem
from test_game_batch_preparation import create, config, preparation, references, Requester


def task_config(**changes):
    return config(pre_translation_data=[],post_translation_data=[],exclusion_list_data=[],**changes)


@pytest.mark.parametrize('mode',['translate','polish'])
def test_real_task_prepare_and_run_uses_context_and_committer(tmp_path,monkeypatch,mode):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,units,items=create(tmp_path)
    requester=Requester()
    requester_module=importlib.import_module('ModuleFolders.Infrastructure.LLMRequester.LLMRequester')
    monkeypatch.setattr(requester_module,'LLMRequester',lambda:requester)
    monkeypatch.delenv('AINIEE_OFFLINE',raising=False)
    try:
        if mode=='polish':
            store.commit(TranslationProposal('u2','原文已译',units[2].source_hash,0,origin='manual'))
            items=list(build_projection(store).items_iter())
            from ModuleFolders.Service.TaskExecutor.PolisherTask import PolisherTask
            task=PolisherTask(task_config(),None)
        else:
            from ModuleFolders.Service.TaskExecutor.TranslatorTask import TranslatorTask
            task=TranslatorTask(task_config(),None,'ja')
        task.set_items([items[2]]); task.set_previous_items(items[:2])
        if mode=='polish': task.prepare(game_preparation=preparation(store.root))
        else: task.prepare('synthetic-platform',game_preparation=preparation(store.root))
        refs=references(task._game_batch)
        assert [r['unit_id'] for r in refs['previous']]==(['u1'] if mode=='polish' else ['u0','u1'])
        result=task.unit_polish_task() if mode=='polish' else task.unit_translation_task()
        assert result['check_result'] and result['row_count']==1
        assert list(requester.calls[0])==['u2']
        assert store.translation('u2')['origin']==mode
        assert items[2].translated_text==store.translation('u2')['text']
        assert store.translation('u1') is None and store.translation('u3') is None
        assert store.jobs()[-1]['operation']==('POLISH' if mode=='polish' else 'TRANSLATE')
        estimates=task._game_batch.token_estimates
        assert estimates['requested']>0 and estimates['reference']>0
        assert estimates['expected_output']>0 and estimates['reusable']==0
        assert estimates['total']==task.request_tokens_consume
    finally: store.close()


def test_table_operation_reuses_one_snapshot_for_multiple_requests(tmp_path,monkeypatch):
    from test_game_scene_requests import table
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,_=create(tmp_path,scenes=['a']*41)
    manager=SimpleNamespace(project=build_projection(store))
    try:
        original=ProjectStore.units
        with patch.object(ProjectStore,'units',autospec=True,side_effect=original) as reads:
            result=table(manager,list(range(41)),Requester())
        assert result=={'row_count':41,'error':''}
        assert reads.call_count==1
        assert len(store.jobs())==3
    finally: store.close()


@pytest.mark.parametrize('mode',['translate','polish'])
def test_main_preparation_round_shares_graph_and_stops_before_provider(tmp_path,monkeypatch,mode):
    """Execute actual main entry until its existing preparation cancellation gate."""
    executor_module=importlib.import_module('ModuleFolders.Service.TaskExecutor.TaskExecutor')
    store,units,_=create(tmp_path)
    try:
        if mode=='polish':
            for unit in units:
                store.commit(TranslationProposal(unit.unit_id,'有效译文',unit.source_hash,0,origin='manual'))
        host=object.__new__(CacheManager); host.project=build_projection(store)
        executor=object.__new__(executor_module.TaskExecutor)
        executor.cache_manager=host
        values=dict(initialize=lambda *_:None,prepare_for_active_platform=lambda *_:None,
            load_project_table_data=lambda *_:None,rpm_limit=60,round_limit=1,
            tokens_limit_switch=False,lines_limit=1,tokens_limit=100,
            source_language='ja',target_language='zh',target_platform='synthetic')
        values.update(label_output_path=str(store.root/'AiNieeOutput'),
            label_polish_output_path=str(store.root/'AiNieePolishOutput'))
        executor.config=task_config(**values)
        executor.request_limiter=SimpleNamespace(set_limit=lambda *_:None)
        executor.text_filter=SimpleNamespace(filter_project=lambda *_:None)
        executor.emit=lambda *_:None; executor.info=lambda *_:None; executor.print=lambda *_:None
        cls=executor_module.TranslatorTask if mode=='translate' else executor_module.PolisherTask
        original_prepare=cls.prepare; collected=[]
        def stop_after_third(task,*args,**kwargs):
            original_prepare(task,*args,**kwargs); collected.append(task._game_batch)
            if len(collected)==3: Base.work_status=Base.STATUS.STOPING
        monkeypatch.setattr(cls,'prepare',stop_after_third)
        monkeypatch.setattr(executor_module.GlossaryHelper,'clear_cache',lambda:None)
        # A deterministic tokenizer stub isolates graph/caller behavior in this test.
        # The separate real preparation benchmark includes the installed tokenizer.
        from ModuleFolders.Infrastructure.Tokener.Tokener import Tokener
        monkeypatch.setattr(Tokener,'calculate_tokens',lambda self,messages,prompt:sum(len(m['content']) for m in messages)+len(prompt))
        monkeypatch.setattr(Tokener,'num_tokens_from_str',lambda self,text:len(text))
        original=ProjectStore.units
        with patch.object(ProjectStore,'units',autospec=True,side_effect=original) as reads:
            if mode=='translate': executor.translation_start_target(False)
            else: executor.polish_start_target(False)
        assert len(collected)==3 and reads.call_count==1
        assert Base.work_status==Base.STATUS.TASKSTOPPED
        assert [b.units[0].unit_id for b in collected]==['u0','u1','u2']
        assert [r['unit_id'] for r in references(collected[2])['previous']]==(
            ['u1'] if mode=='polish' else ['u0','u1'])
        assert store.jobs()==[]
    finally: store.close()


@pytest.mark.parametrize('mode',['translate','polish'])
def test_ordinary_document_prepare_keeps_existing_prompt_path(monkeypatch,mode):
    if mode=='translate':
        module=importlib.import_module('ModuleFolders.Service.TaskExecutor.TranslatorTask')
        task=module.TranslatorTask(task_config(),None,'ja')
        monkeypatch.setattr(task.text_processor,'replace_all',lambda *_:({'0':'ordinary'},{},{},{},{}))
        monkeypatch.setattr(module.PromptBuilder,'generate_prompt',lambda *_:([], 'ordinary prompt',[]))
    else:
        module=importlib.import_module('ModuleFolders.Service.TaskExecutor.PolisherTask')
        task=module.PolisherTask(task_config(),None)
        monkeypatch.setattr(task.text_processor,'replace_all',lambda _config,value:value)
        monkeypatch.setattr(module.PromptBuilderPolishing,'generate_prompt',lambda *_:([],'ordinary prompt',[]))
    monkeypatch.setattr(module.Tokener,'calculate_tokens',lambda *_:1)
    task.set_items([CacheItem(source_text='ordinary',translated_text='translated')])
    task.set_previous_items([CacheItem(source_text='previous')])
    if mode=='translate':
        task.config.translation_prompt_selection={'last_selected_id':'common'}
        task.prepare('synthetic')
    else: task.prepare()
    assert task._game_batch is None
    assert task.previous_text_list==['previous'] and task.source_text_dict=={'0':'ordinary'}
    assert task.system_prompt=='ordinary prompt'
