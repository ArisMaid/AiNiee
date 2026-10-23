"""Complete actual main controller -> local response -> export -> static report."""
import importlib,json,threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Domain.FileOutputer.FileOutputer import FileOutputer
from ModuleFolders.Domain.TranslationResultCheck.TranslationResultCheck import TranslationResultCheck
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
from ModuleFolders.Infrastructure.RequestLimiter.RequestLimiter import RequestLimiter
from test_game_output_policy import case,executor_shell
from test_game_task_reset import manager


@pytest.mark.parametrize('mode',['translate','polish'])
@pytest.mark.parametrize('switch_point',['none','done','provider'])
def test_actual_main_flow_publishes_exchange_and_role_correct_quality(tmp_path,monkeypatch,mode,switch_point):
    store,units,_,source=case(tmp_path)
    other,_,foreign,_=case(tmp_path/'foreign')
    module,executor=executor_shell(None)
    requester=Mock()
    def reply(messages,*_):
        targets=json.loads(messages[-1]['content'])
        if switch_point=='provider':executor.cache_manager.project=foreign
        return False,'',json.dumps({key:'有效译文'+key for key in targets},ensure_ascii=False),1,1
    requester.sent_request.side_effect=reply
    requester_module=importlib.import_module('ModuleFolders.Infrastructure.LLMRequester.LLMRequester')
    monkeypatch.setattr(requester_module,'LLMRequester',lambda:requester)
    monkeypatch.delenv('AINIEE_OFFLINE',raising=False)
    from ModuleFolders.Config.FilePathConfig import bundled_tiktoken_cache_dir
    monkeypatch.setenv('TIKTOKEN_CACHE_DIR',str(bundled_tiktoken_cache_dir()))
    # Remove only cosmetic/autosave waits; real threads, requester dispatch,
    # SQLite authority and writers/report algorithms are exercised unchanged.
    monkeypatch.setattr(module.time,'sleep',lambda *_:None)
    monkeypatch.setattr(Base,'work_status',Base.STATUS.IDLE)
    try:
        if mode=='polish':
            for unit in units:
                tr=store.translation(unit.unit_id) or {}
                store.commit(TranslationProposal(unit.unit_id,'有效旧稿',unit.source_hash,tr.get('revision',0),origin='manual'))
        executor.cache_manager=manager(build_projection(store));executor.cache_manager.require_save_to_file=Mock()
        executor._executor_lock=threading.RLock();executor._active_executor=None
        executor.request_limiter=RequestLimiter()
        executor.text_filter=SimpleNamespace(filter_project=lambda *_:None)
        executor.file_writer=FileOutputer();executor.translation_result_check=TranslationResultCheck()
        executor.config=SimpleNamespace(initialize=lambda *_:None,prepare_for_active_platform=lambda *_:None,
            load_project_table_data=lambda *_:None,request_timeout=5,round_limit=1,rpm_limit=60,
            pre_translation_data=[],post_translation_data=[],exclusion_list_data=[],project_terms_data=[],
            pre_line_counts=2,polishing_pre_line_counts=2,tokens_limit_switch=False,lines_limit=99,tokens_limit=999,
            source_language='japanese',target_language='chinese_simplified',target_platform='local-test',
            translation_project='RpgGame',platforms={'local-test':{'name':'local stub'}},
            base_url='unused',model='local-stub',actual_thread_counts=1,
            translation_prompt_selection={'last_selected_id':'owner-test','prompt_content':'owner test'},
            polishing_prompt_selection={'last_selected_id':'owner-test','prompt_content':'owner test'},
            response_conversion_toggle=False,output_filename_suffix='_translated',bilingual_text_order='source_first',
            label_input_path=str(store.root/'game-project.json'),
            label_output_path=str(store.root/'AiNieeOutput'),label_polish_output_path=str(store.root/'AiNieePolishOutput'),
            translation_result_check_switch=True,exclusion_list_switch=False,auto_process_text_code_segment=False,
            get_active_platform_configuration=lambda:{})
        output=store.root/('AiNieeOutput' if mode=='translate' else 'AiNieePolishOutput')
        report_ready_at_done=[]
        def emitted(event,data):
            if event==Base.EVENT.TASK_STOP_DONE:
                assert data['game_project_root']==str(store.root)
                assert data['project_id']==store.metadata()['project_id']
                report_ready_at_done.append(bool(list(output.glob('game-validation-*.json'))))
                if switch_point=='done':executor.cache_manager.project=foreign
        executor.emit=emitted
        foreign_before=other.translation('u0');foreign_meta=other.metadata();foreign_jobs=other.jobs()
        def execute():
            if mode=='translate':executor.translation_start_target(False)
            else:executor.polish_start_target(False)
        if switch_point=='provider':
            with pytest.raises(ValueError,match='PROJECT.*CHANGED|CONTEXT.*CHANGED'):execute()
            assert not output.exists()
            assert other.translation('u0')==foreign_before and other.metadata()==foreign_meta and other.jobs()==foreign_jobs
            assert requester.sent_request.call_count==1
            return
        execute()
        assert requester.sent_request.call_count==1
        reports=list(output.glob('game-validation-*.json'));exchanges=list(output.glob('game-translations-*.json'))
        assert len(reports)==len(exchanges)==1
        report=json.loads(reports[0].read_text(encoding='utf-8'))
        assert report['passed'] and report['deterministic']['untranslated']==0
        assert report['runtime_validation']=='not_run' and report['model_quality_validation']=='not_run'
        assert report['quality']['errors']==[]
        assert len(list(output.iterdir()))==2
        assert (source/'keep.txt').read_text(encoding='utf-8')=='source stays'
        assert store.jobs()[-1]['run_state']=='COMPLETED'
        coordinator=coordinator_for(executor.cache_manager);task_scope=coordinator.current
        assert store.jobs()[-1]['payload']['game_execution_id']==task_scope.execution_id
        assert store.jobs()[-1]['payload']['dataset_revision']==task_scope.dataset_revision
        assert coordinator.job_ids(task_scope)==(store.jobs()[-1]['job_id'],)
        assert coordinator.active_job_ids(task_scope)==()
        assert Base.work_status==Base.STATUS.TASKSTOPPED and executor._active_executor is None
        assert report_ready_at_done==[True]
        assert other.translation('u0')==foreign_before and other.metadata()==foreign_meta and other.jobs()==foreign_jobs
    finally:store.close();other.close()
