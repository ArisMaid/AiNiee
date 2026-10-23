import os
import time
import threading
from functools import partial
import concurrent.futures

import opencc
import shutil
import tempfile
from tqdm import tqdm


# 缓存临时目录路径，避免重复创建
_opencc_temp_dir = None

def _create_opencc_converter(preset: str) -> opencc.OpenCC:
    """创建 opencc 转换器，处理 Windows 下路径包含非 ASCII 字符导致 C 扩展失败的问题"""
    global _opencc_temp_dir

    use_temp_dir = os.name == "nt"
    if not use_temp_dir:
        try:
            return opencc.OpenCC(preset)
        except (RuntimeError, OSError) as e:
            # 仅对路径相关错误进行 fallback，避免吞掉不相关的 bug
            error_msg = str(e).lower()
            if "not found" not in error_msg and "not accessible" not in error_msg:
                raise
            use_temp_dir = True

    if use_temp_dir and _opencc_temp_dir is None:
        opencc_dir = os.path.dirname(opencc.__file__)
        share_dir = os.path.join(opencc_dir, "clib", "share", "opencc")
        candidate_roots = [tempfile.gettempdir()]
        if os.name == "nt":
            candidate_roots.append(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Temp"))

        temp_dir = None
        last_error = None
        for root in candidate_roots:
            try:
                os.makedirs(root, exist_ok=True)
                candidate_dir = tempfile.mkdtemp(prefix="opencc_", dir=root)
                try:
                    candidate_dir.encode("ascii")
                except UnicodeEncodeError:
                    # Retain this diagnostic directory; cleanup is always manual.
                    continue
                temp_dir = candidate_dir
                break
            except OSError as error:
                last_error = error

        if temp_dir is None:
            raise RuntimeError("无法创建纯 ASCII 路径的 OpenCC 临时目录") from last_error

        try:
            shutil.copytree(share_dir, temp_dir, dirs_exist_ok=True)
        except Exception:
            raise
        _opencc_temp_dir = temp_dir
        # Keep dictionary copies after shutdown; never recursively remove files.

    config_name = preset if preset.endswith(".json") else preset + ".json"
    return opencc.OpenCC(os.path.join(_opencc_temp_dir, config_name))

from ModuleFolders.Base.Base import Base
from ModuleFolders.Config.Config import ConfigMixin
from ModuleFolders.Log.Log import LogMixin
from ModuleFolders.Service.Cache.CacheItem import TranslationStatus
from ModuleFolders.Service.Cache.CacheManager import CacheManager
from ModuleFolders.Service.Cache.CacheProject import CacheProjectStatistics
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
from ModuleFolders.Service.TaskExecutor.AnalysisTask import AnalysisTask
from ModuleFolders.Service.TaskExecutor.TranslatorTask import TranslatorTask
from ModuleFolders.Service.TaskExecutor.PolisherTask import PolisherTask
from ModuleFolders.Service.TaskExecutor.ProofreadTask import ProofreadTask
from ModuleFolders.Infrastructure.TaskConfig.TaskConfig import TaskConfig
from ModuleFolders.Domain.PromptBuilder.PromptBuilder import PromptBuilder
from ModuleFolders.Domain.PromptBuilder.PromptBuilderPolishing import PromptBuilderPolishing
from ModuleFolders.Domain.PromptBuilder.PromptBuilderEnum import PromptBuilderEnum
from ModuleFolders.Domain.PromptBuilder.PromptBuilderLocal import PromptBuilderLocal
from ModuleFolders.Domain.PromptBuilder.PromptBuilderSakura import PromptBuilderSakura
from ModuleFolders.Domain.PromptBuilder.GlossaryHelper import GlossaryHelper
from ModuleFolders.Domain.TextFilter.TextFilter import TextFilter
from ModuleFolders.Domain.TranslationResultCheck.TranslationResultCheck import TranslationResultCheck
from ModuleFolders.Infrastructure.LLMRequester.LLMClientFactory import LLMClientFactory
from ModuleFolders.Infrastructure.RequestLimiter.RequestLimiter import RequestLimiter
from ModuleFolders.Service.TaskExecutor.TranslatorUtil import (
    get_most_common_language,
    get_source_language_for_file,
    map_language_name_to_code,
)


# 翻译器
class TaskExecutor(ConfigMixin, LogMixin, Base):

    def __init__(self, cache_manager, file_reader, file_writer) -> None:
        super().__init__()

        # 初始化
        self.cache_manager = cache_manager
        self.file_reader = file_reader
        self.file_writer = file_writer
        self.config = TaskConfig()
        self.text_filter = TextFilter()
        self.translation_result_check = TranslationResultCheck()
        self.request_limiter = RequestLimiter()
        self._executor_lock = threading.RLock()
        self._active_executor = None

        # 注册事件
        self.subscribe(Base.EVENT.ANALYSIS_TASK_START, self.analysis_task_start)
        self.subscribe(Base.EVENT.TABLE_PROOFREAD_START, self.table_proofread_start)
        self.subscribe(Base.EVENT.TASK_STOP, self.task_stop)
        self.subscribe(Base.EVENT.TASK_START, self.task_start)
        self.subscribe(Base.EVENT.TASK_MANUAL_EXPORT, self.task_manual_export)
        self.subscribe(Base.EVENT.APP_SHUT_DOWN, self.app_shut_down)

    def _set_active_executor(self, executor: concurrent.futures.ThreadPoolExecutor) -> None:
        with self._executor_lock:
            self._active_executor = executor

    def _clear_active_executor(self, executor: concurrent.futures.ThreadPoolExecutor) -> None:
        with self._executor_lock:
            if self._active_executor is executor:
                self._active_executor = None

    def _cancel_active_executor(self) -> None:
        with self._executor_lock:
            executor = self._active_executor

        if executor is None:
            return

        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)

    def _resolve_output_source_language(self, configured_source: str | None) -> str | None:
        """解析输出文件使用的原文语言，保留翻译阶段的逐文件自动检测。"""
        if configured_source != "auto":
            return map_language_name_to_code(configured_source) if configured_source else None

        detected_language = get_most_common_language(self.cache_manager.project)
        if detected_language == "un":
            return None

        return map_language_name_to_code(detected_language)

    @staticmethod
    def _resolve_output_target_language(configured_target: str | None) -> str | None:
        """将输出文件使用的译文语言名称转换为 BCP 47 代码。"""
        return map_language_name_to_code(configured_target) if configured_target else None

    def _convert_translated_text_with_opencc(self, preset: str | None, *, project=None) -> bool:
        preset = preset or "s2t"
        self.print("")
        self.info(f"已启动自动简繁转换功能，正在使用 {preset} 配置进行字形转换 ...")
        self.print("")

        try:
            converter = _create_opencc_converter(preset)
            from types import SimpleNamespace
            cache=self.cache_manager if project is None else SimpleNamespace(project=project)
            cache_list = cache.project.items_iter()
            for item in cache_list:
                if item.translation_status in (TranslationStatus.TRANSLATED, TranslationStatus.POLISHED):
                    if item.get_extra('game_project_root'):
                        from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
                        from ModuleFolders.Service.GameProject.TranslationCommitter import TranslationCommitter
                        from ModuleFolders.Service.GameProject.CacheBridge import route_cache_edit
                        with ProjectStore(item.get_extra('game_project_root')) as store:
                            protected = TranslationCommitter(store).policy.protect(item.translated_text,
                                item.get_extra('unit_id'))
                            converted, issues = protected.restore(converter.convert(protected.text))
                            if issues:
                                raise ValueError('OpenCC changed protected game controls')
                        route_cache_edit(cache, item.get_extra('game_storage_path'), item.text_index,
                            'translated_text', converted, origin='opencc')
                        continue
                    item.translated_text = converter.convert(item.translated_text)
        except Exception as error:
            self.print("")
            self.error(f"简繁转换失败，已取消本次输出：{error}", error)
            self.print("")
            return False

        self.print("")
        self.info("简繁转换完成。")
        self.print("")
        return True

    # 应用关闭事件
    def app_shut_down(self, event: int, data: dict) -> None:
        coordinator=getattr(getattr(self,'cache_manager',None),'_game_task_coordinator',None)
        if coordinator is not None:
            scope=coordinator.stop_current()
            if scope is not None:
                self._cancel_game_execution(scope)
                return
        Base.work_status = Base.STATUS.STOPING
        self._cancel_active_executor()
        LLMClientFactory().close_all_clients()

    def analysis_task_start(self, event: int, data: dict) -> None:
        from ModuleFolders.Service.GameProject.GameAnalysisExecution import handle_analysis_start
        if handle_analysis_start(self,data):return
        if Base.work_status != Base.STATUS.IDLE:
            return
        Base.work_status = Base.STATUS.ANALYSIS_TASK
        threading.Thread(target=self.analysis_start_target, daemon=True).start()

    def table_proofread_start(self, event: int, data: dict) -> None:
        from ModuleFolders.Service.GameProject.GameTableExecution import handle_table_start
        if handle_table_start(self,data,'proofread',self.table_proofread_start_target):return
        if Base.work_status not in (Base.STATUS.IDLE, Base.STATUS.TABLE_TASK):
            return

        with self._executor_lock:
            if self._active_executor is not None:
                return

        Base.work_status = Base.STATUS.TABLE_TASK
        threading.Thread(
            target=self.table_proofread_start_target,
            args=(data,),
            daemon=True,
        ).start()

    def analysis_start_target(self,*,task_scope=None,config=None,requester=None) -> None:
        from ModuleFolders.Service.GameProject.GameCacheIdentity import is_game_projection
        if task_scope is not None or is_game_projection(self.cache_manager.project):
            from ModuleFolders.Service.GameProject.GameAnalysisExecution import run_game_analysis
            return run_game_analysis(self,task_scope=task_scope,config=config,requester=requester)
        try:
            analysis_task = AnalysisTask(
                self.cache_manager,
                self._set_active_executor,
                self._clear_active_executor,
            )
            analysis_task.run()
        except Exception as error:
            self.error(
                f"分析任务执行失败: {error}",
                error,
            )
            Base.work_status = Base.STATUS.IDLE
            self.emit(
                Base.EVENT.ANALYSIS_TASK_DONE,
                {"status": "error", "analysis_data": None, "message": str(error)},
            )

    # Table proofreading task event
    def table_proofread_start_target(self, data: dict,*,task_scope=None,config=None,requester=None):
        from ModuleFolders.Service.GameProject.GameCacheIdentity import is_game_projection
        from ModuleFolders.Service.GameProject.GameTaskScope import has_game_scope
        if task_scope is not None or is_game_projection(self.cache_manager.project) or has_game_scope(data):
            from ModuleFolders.Service.GameProject.GameTableExecution import run_table_group
            return run_table_group(self,data,'proofread',task_scope=task_scope,
                config=config,requester=requester,config_factory=TaskConfig)
        try:
            proofread_task = ProofreadTask(
                data,
                self._set_active_executor,
                self._clear_active_executor,
            )
            proofread_task.run()
        except Exception as error:
            self.error(
                f"AI 自动校对任务执行失败：{error}",
                error,
            )
            if Base.work_status == Base.STATUS.STOPING:
                Base.work_status = Base.STATUS.TASKSTOPPED
            else:
                Base.work_status = Base.STATUS.IDLE

    # 手动导出事件
    def task_manual_export(self, event: int, data: dict) -> None:

        self.print("")
        self.info(f"正在读取数据，准备输出中 ...")
        self.print("")

        # 获取配置信息，此时 config 是一个字典，后面需要使用get
        config = self.load_config()
        
        output_path = data.get("export_path")
        inpput_path = config.get("label_input_path")
        export_project=self.cache_manager.project

        try:
            from ModuleFolders.Service.GameProject.GameOutputPolicy import preflight_game_output
            checked_output=preflight_game_output(export_project,output_path)
            scope=(export_project,export_project.get_extra('game_project_root'),export_project.project_id) if checked_output is not None else None
            self._assert_game_output_scope(scope,stop_task=False)
        except (ValueError,OSError) as error:
            self.error(f"导出失败：{error}",error)
            return

        # 如果开启了转换简繁开关功能，则进行文本转换
        if config.get("response_conversion_toggle"):  # 使用 .get()
            if not self._convert_translated_text_with_opencc(config.get("opencc_preset"),
                    **({'project':export_project} if scope is not None else {})):
                return

        # 输出配置包
        output_config = {
            "translated_suffix": config.get('output_filename_suffix'),
            "bilingual_suffix": "_bilingual",
            "bilingual_order": config.get('bilingual_text_order','translation_first'),
            "source_lang_code": self._resolve_output_source_language(config.get('source_language')),
            "target_lang_code": self._resolve_output_target_language(config.get('target_language')),
        }

        # 写入文件
        try:
            self._assert_game_output_scope(scope,stop_task=False)
            self.file_writer.output_translated_content(
                export_project if scope is not None else self.cache_manager.project,
                checked_output if scope is not None else output_path,
                inpput_path,
                output_config,
            )
        except Exception as error:
            self.print("")
            self.error(f"导出失败：{error}", error)
            self.print("")
            return

        self.print("")
        self.info(f"翻译结果已成功保存至 {output_path} 目录。")
        self.print("")

    # 任务停止事件
    def task_stop(self, event: int, data: dict) -> None:
        from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for,has_game_scope
        from ModuleFolders.Service.GameProject.GameCacheIdentity import is_game_projection
        if is_game_projection(self.cache_manager.project) or has_game_scope(data):
            coordinator=coordinator_for(self.cache_manager)
            scope=coordinator.current
            if not coordinator.request_stop(self.cache_manager.project,data):return
            self._cancel_game_execution(scope)
            # The main wrapper emits its own terminal scope after all work joins.
            return
        # 设置运行状态为停止中
        Base.work_status = Base.STATUS.STOPING
        self._cancel_active_executor()
        LLMClientFactory().close_all_clients()

        def target() -> None:
            while True:
                time.sleep(0.5)
                if Base.work_status in (Base.STATUS.TASKSTOPPED, Base.STATUS.IDLE):
                    self.print("")
                    self.info("任务已停止 ...")
                    self.print("")
                    self.emit(Base.EVENT.TASK_STOP_DONE, {})
                    break

        # 子线程循环检测停止状态
        threading.Thread(target = target).start()

    def _cancel_game_execution(self,scope):
        from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
        coordinator=coordinator_for(self.cache_manager)
        def cancel_owned():
            Base.work_status=Base.STATUS.STOPING
            self._cancel_active_executor()
            coordinator.cancel_pending(scope)
            from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
            from ModuleFolders.Service.GameProject.JobControl import request_action
            try:
                with ProjectStore(scope.root) as store:
                    for job_id in coordinator.active_job_ids(scope):
                        try:request_action(store,job_id,'cancel')
                        except ValueError as error:
                            if not str(error).startswith('JOB_ACTION_REFUSED:'):raise
            except (ValueError,OSError) as error:self.warning('游戏请求取消登记未完成：'+str(error))
            finally:LLMClientFactory().close_all_clients()
        coordinator.run_if_active(scope,cancel_owned)

    # 任务开始事件
    def task_start(self, event: int, data: dict) -> None:
        # 获取配置信息
        continue_status = data.get("continue_status")
        current_mode = data.get("current_mode")
        start_project=self.cache_manager.project
        from ModuleFolders.Service.GameProject.GameCacheIdentity import is_game_projection
        from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for,has_game_scope
        coordinator=coordinator_for(self.cache_manager)
        task_scope=None
        if is_game_projection(self.cache_manager.project) or has_game_scope(data):
            try:
                if not is_game_projection(self.cache_manager.project):raise ValueError('GAME_TASK_START_CONTEXT_INVALID')
                task_scope=coordinator.accept(self.cache_manager.project,data)
            except ValueError as error:
                self.warning('游戏任务开始通知已拒绝：'+str(error))
                return
            operation='translate' if current_mode==TaskType.TRANSLATION else 'polish' if current_mode==TaskType.POLISH else None
            try:
                if type(current_mode) is not int or task_scope.operation!=operation:
                    raise ValueError('GAME_TASK_OPERATION_INVALID')
                task_scope.validate_canonical(self.cache_manager.project)
            except (ValueError,OSError) as error:
                self._finish_game_task(task_scope,error=str(error))
                return
        elif coordinator.active:
            self.warning('游戏任务仍在执行，不能启动其他工程。')
            return

        def run_task_target(target_func, *args) -> None:
            try:
                if self.cache_manager.project is not start_project:raise ValueError('TASK_START_PROJECT_CHANGED')
                if task_scope is None:target_func(*args)
                else:target_func(*args,task_scope=task_scope)
            except Exception as e:
                self.print("")
                self.error(f"任务启动失败或执行异常 ... {e}", e)
                self.print("")

                if task_scope is not None:self._finish_game_task(task_scope,error=str(e))
                else:
                    Base.work_status = Base.STATUS.TASKSTOPPED
                    self._cancel_active_executor()
                    LLMClientFactory().close_all_clients()
                    self.emit(Base.EVENT.TASK_STOP_DONE, {})
            finally:
                if task_scope is not None:self._finish_game_task(task_scope)

        # 翻译任务
        if current_mode == TaskType.TRANSLATION:
            target=self.translation_start_target
        
        # 润色任务
        elif current_mode == TaskType.POLISH:
            target=self.polish_start_target

        else:
            self.print("")
            self.error(f"非法的翻译模式：{current_mode}，请检查配置文件 ...")
            self.print("")
            return None
        if task_scope is None:Base.work_status=Base.STATUS.TASKING
        try:
            threading.Thread(target=run_task_target,args=(target,continue_status)).start()
        except Exception as error:
            if task_scope is not None:self._finish_game_task(task_scope,error=str(error))
            raise

    def _emit_game_task_event(self,task_scope,event,data):
        if task_scope is None:
            self.emit(event,data)
            return
        from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
        coordinator=coordinator_for(self.cache_manager)
        if coordinator.current is not task_scope:return
        if event==Base.EVENT.TASK_STOP_DONE:
            if not coordinator.finish(task_scope):return
        else:
            if event==Base.EVENT.TASK_COMPLETED and not task_scope.matches(self.cache_manager.project,task_scope.payload()):return
            coordinator.assert_owner(task_scope,self.cache_manager.project,allow_terminal=event==Base.EVENT.TASK_COMPLETED)
        packet={**data,**task_scope.payload()}
        if event==Base.EVENT.TASK_UPDATE and 'total_requests' in data:
            # The counter was captured with all metrics under the stats lock.
            # Saving/queued delivery may reorder callbacks after that snapshot.
            packet['game_progress_revision']=data['total_requests']
        self.emit(event,packet)

    def _finish_game_task(self,task_scope,*,error=''):
        from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
        if coordinator_for(self.cache_manager).finish(task_scope):
            Base.work_status=Base.STATUS.TASKSTOPPED
            self.emit(Base.EVENT.TASK_STOP_DONE,{**task_scope.payload(),'error':error})

    def _bind_game_job(self,task_scope,info):
        from ModuleFolders.Service.GameProject.GameTaskScope import bind_game_job
        bind_game_job(self.cache_manager,task_scope,info)

    def _release_game_job(self,task_scope,info):
        from ModuleFolders.Service.GameProject.GameTaskScope import release_game_job
        release_game_job(self.cache_manager,task_scope,info)

    def _bind_task_execution(self,task,task_scope):
        if task_scope is not None:
            task.bind_game_execution(task_scope,partial(self._bind_game_job,task_scope),
                partial(self._release_game_job,task_scope))

    def _sync_game_progress(self,task_scope,continuing):
        if task_scope is None:return
        from ModuleFolders.Service.GameProject.GameTaskScope import game_task_progress
        progress=game_task_progress(task_scope.project,task_scope.operation)
        with self.project_status_data.atomic_scope():
            self.project_status_data.line=progress['completed'] if continuing else 0
            self.project_status_data.total_line=progress['total'] if continuing else progress['pending']

    def _run_main_operation(self,operation,continue_status,task_scope=None):
        from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
        from ModuleFolders.Service.GameProject.GameCacheIdentity import is_game_projection
        direct=task_scope is None
        start_project=self.cache_manager.project
        try:
            if direct and is_game_projection(start_project):
                coordinator=coordinator_for(self.cache_manager)
                task_scope=coordinator.reserve_current(self.cache_manager,operation,
                    on_claim=lambda:setattr(Base,'work_status',Base.STATUS.TASKING))
                start_project=task_scope.project
                coordinator.accept(start_project,task_scope.payload())
            if task_scope is not None:
                coordinator=coordinator_for(self.cache_manager)
                coordinator.assert_owner(task_scope,self.cache_manager.project)
                if coordinator.stop_requested(task_scope):return
                task_scope.validate_canonical(self.cache_manager.project,check_items=direct)
            implementation=self._translation_start_impl if operation=='translate' else self._polish_start_impl
            return implementation(continue_status,task_scope=task_scope,expected_project=start_project)
        except Exception as error:
            if task_scope is not None:self._finish_game_task(task_scope,error=str(error))
            raise
        finally:
            if task_scope is not None:self._finish_game_task(task_scope)

    def translation_start_target(self,continue_status:bool,*,task_scope=None):
        return self._run_main_operation('translate',continue_status,task_scope)

    def polish_start_target(self,continue_status:bool,*,task_scope=None):
        return self._run_main_operation('polish',continue_status,task_scope)

    # 翻译主流程
    def _preflight_task_output(self, output_path,*,task_scope=None):
        from ModuleFolders.Service.GameProject.GameOutputPolicy import preflight_game_output
        try:return preflight_game_output(self.cache_manager.project,output_path)
        except (ValueError,OSError):
            Base.work_status=Base.STATUS.TASKSTOPPED
            self._emit_game_task_event(task_scope,Base.EVENT.TASK_STOP_DONE,{})
            raise

    def _assert_game_output_scope(self, scope, *, stop_task=True,task_scope=None):
        if scope is None:return
        project,root,identity=scope
        if (self.cache_manager.project is not project or project.get_extra('game_project_root')!=root
                or project.project_id!=identity):
            if stop_task:
                Base.work_status=Base.STATUS.TASKSTOPPED
                self._emit_game_task_event(task_scope,Base.EVENT.TASK_STOP_DONE,{'game_project_root':root,'project_id':identity})
            raise ValueError('GAME_OUTPUT_PROJECT_CONTEXT_CHANGED: output aborted; reload the intended project')
        if task_scope is not None:
            from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
            coordinator_for(self.cache_manager).assert_owner(task_scope,self.cache_manager.project)

    def _translation_start_impl(self, continue_status: bool,*,task_scope=None,expected_project=None) -> None:

        # 设置翻译状态为正在翻译状态
        if task_scope is None:Base.work_status = Base.STATUS.TASKING

        # 读取配置文件，并保存到该类中
        self.config.initialize("translate")

        # 配置当前激活接口信息
        self.config.prepare_for_active_platform("translate")
        self.config.load_project_table_data(self.cache_manager)
        if expected_project is not None and self.cache_manager.project is not expected_project:
            raise ValueError('TASK_START_PROJECT_CHANGED')

        execution_project=self.cache_manager.project
        checked_output=self._preflight_task_output(getattr(self.config,'label_output_path',None),task_scope=task_scope)
        scope=(execution_project,execution_project.get_extra('game_project_root'),execution_project.project_id) if checked_output is not None else None

        # 配置请求限制器
        self.request_limiter.set_limit(self.config.rpm_limit)

        # 初开始翻译时，生成监控数据
        if continue_status == False:
            self.project_status_data = CacheProjectStatistics()
            self.cache_manager.project.stats_data = self.project_status_data
        # 继续翻译时加载存储的监控数据
        else:
            self.project_status_data = self.cache_manager.project.stats_data
            self.project_status_data.start_time = time.time() # 重置开始时间
            self.project_status_data.total_completion_tokens = 0 # 重置完成的token数量

        # 重新同步计数器以反映缓存的当前真实状态（未考虑到被过滤条目）    
        
        # 更新监控面板信息
        self._sync_game_progress(task_scope,continue_status)
        self._emit_game_task_event(task_scope,Base.EVENT.TASK_UPDATE, self.project_status_data.to_dict())

        # 无效文本过滤
        self.text_filter.filter_project(self.config, self.cache_manager.project)

        # 根据最大轮次循环
        round_limit=min(self.config.round_limit,3) if task_scope is not None else self.config.round_limit
        for current_round in range(round_limit + 1):
            self._assert_game_output_scope(scope,task_scope=task_scope)
            # 检测是否需要停止任务
            if Base.work_status == Base.STATUS.STOPING:
                # 循环次数比实际最大轮次要多一轮，当触发停止翻译的事件时，最后都会从这里退出任务
                # 执行到这里说明停止任意的任务已经执行完毕，可以重置内部状态了
                Base.work_status = Base.STATUS.TASKSTOPPED
                return None

            # 获取 待翻译 状态的条目数量
            item_count_status_untranslated = self.cache_manager.get_item_count_by_status(TranslationStatus.UNTRANSLATED)

            # 判断是否需要继续翻译
            if item_count_status_untranslated == 0:
                self.print("")
                self.info("所有文本均已翻译，翻译任务已结束 ...")
                self.print("")
                break

            # 达到最大翻译轮次时
            if item_count_status_untranslated > 0 and current_round == round_limit:
                self.print("")
                self.warning("已达到最大翻译轮次，仍有部分文本未翻译，请检查结果 ...")
                self.print("")
                break

            # 第一轮时且不是继续翻译时，记录总行数
            if current_round == 0 and continue_status == False:
                self.project_status_data.total_line = item_count_status_untranslated

            # 第二轮开始对半切分
            if current_round > 0:
                self.config.lines_limit = max(1, int(self.config.lines_limit / 2))
                self.config.tokens_limit = max(1, int(self.config.tokens_limit / 2))

            # 生成缓存数据条目片段的合集列表，原文列表与上文列表一一对应
            chunks, previous_chunks, file_paths = self.cache_manager.generate_item_chunks(
                "line" if self.config.tokens_limit_switch == False else "token",
                self.config.lines_limit if self.config.tokens_limit_switch == False else self.config.tokens_limit,
                self.config.pre_line_counts,
                TaskType.TRANSLATION
            )

            # 生成翻译任务合集列表
            tasks_list = []
            if Base.work_status == Base.STATUS.STOPING:
                Base.work_status = Base.STATUS.TASKSTOPPED
                return None
            game_preparation = None
            if chunks and self.cache_manager.project.get_extra('game_project_root'):
                from ModuleFolders.Service.GameProject.GameBatchPreparation import GameBatchPreparation
                game_preparation = GameBatchPreparation(self.cache_manager.project.get_extra('game_project_root'))
            print("")
            self.info(f"正在生成翻译任务 ...")
            for chunk, previous_chunk, file_path in tqdm(zip(chunks, previous_chunks, file_paths),desc="生成翻译任务", total=len(chunks)):
                if Base.work_status == Base.STATUS.STOPING:
                    break

                # 确定该任务的主语言
                language_stats = self.cache_manager.project.get_file(file_path).language_stats # 获取该文件的语言检测数据
                file_source_lang = get_source_language_for_file(self.config.source_language,self.config.target_language,language_stats)

                task = TranslatorTask(self.config, self.request_limiter, file_source_lang)  # 实例化
                task.set_items(chunk)  # 传入该任务待翻译原文
                self._bind_task_execution(task,task_scope)
                task.set_previous_items(previous_chunk)  # 传入该任务待翻译原文的上文
                if game_preparation is not None:
                    task.prepare(self.config.target_platform, game_preparation=game_preparation)
                else:
                    task.prepare(self.config.target_platform)  # 预先构建消息列表
                tasks_list.append(task)
            GlossaryHelper.clear_cache()
            if Base.work_status == Base.STATUS.STOPING:
                Base.work_status = Base.STATUS.TASKSTOPPED
                return None
            self.info(f"已经生成全部翻译任务 ...")
            self.print("")

            # 输出开始翻译的日志
            self.print("")
            self.info(f"当前轮次 - {current_round + 1}")
            self.info(f"最大轮次 - {round_limit}")
            self.info(f"项目类型 - {self.config.translation_project}")
            self.info(f"原文语言 - {self.config.source_language}")
            self.info(f"译文语言 - {self.config.target_language}")
            self.print("")
            self.info(f"接口名称 - {self.config.platforms.get(self.config.target_platform, {}).get('name', '未知')}")
            self.info(f"接口地址 - {self.config.base_url}")
            self.info(f"模型名称 - {self.config.model}")
            self.print("")
            self.info(f"RPM 限额 - {self.config.rpm_limit}")

            # 根据提示词规则打印基础指令
            system = ""
            s_lang = self.config.source_language
            if self.config.target_platform.startswith("LocalLLM"):   # 需要放在前面，以免提示词预设的分支覆盖
                system = PromptBuilderLocal.build_system(self.config, s_lang)
            elif self.config.target_platform.startswith("sakura"):  # 需要放在前面，以免提示词预设的分支覆盖
                system = PromptBuilderSakura.build_system(self.config, s_lang)
            elif self.config.translation_prompt_selection["last_selected_id"] in (PromptBuilderEnum.COMMON, PromptBuilderEnum.COT, PromptBuilderEnum.THINK, PromptBuilderEnum.LOCAL):
                system = PromptBuilder.build_system(self.config, s_lang)
            else:
                system = self.config.translation_prompt_selection["prompt_content"]
            self.print("")
            if system:
                self.info(f"本次任务使用以下基础提示词：\n{system}\n") 

            self.info(f"即将开始执行翻译任务，预计任务总数为 {len(tasks_list)}, 同时执行的任务数量为 {self.config.actual_thread_counts}，请注意保持网络通畅 ...")
            time.sleep(3)
            self.print("")

            # 开始执行翻译任务,构建异步线程池
            executor = concurrent.futures.ThreadPoolExecutor(max_workers = self.config.actual_thread_counts, thread_name_prefix = "translator")
            self._set_active_executor(executor)
            try:
                for task in tasks_list:
                    if Base.work_status == Base.STATUS.STOPING:
                        break

                    try:
                        future = executor.submit(task.start)
                    except RuntimeError:
                        if Base.work_status == Base.STATUS.STOPING:
                            break
                        raise

                    future.add_done_callback(partial(self.task_done_callback,task_scope=task_scope,stats=self.project_status_data))  # 为future对象添加一个回调函数，当任务完成时会被调用，更新数据
            finally:
                try:
                    executor.shutdown(wait=True, cancel_futures=Base.work_status == Base.STATUS.STOPING)
                finally:
                    self._clear_active_executor(executor)

        # 等待可能存在的缓存文件写入请求处理完毕
        time.sleep(CacheManager.SAVE_INTERVAL)

        # 如果开启了转换简繁开关功能，则进行文本转换
        self._assert_game_output_scope(scope,task_scope=task_scope)
        if self.config.response_conversion_toggle:
            if not self._convert_translated_text_with_opencc(self.config.opencc_preset,
                    **({'project':execution_project} if scope is not None else {})):
                Base.work_status = Base.STATUS.TASKSTOPPED
                self._emit_game_task_event(task_scope,Base.EVENT.TASK_STOP_DONE, {})
                return

        # 输出配置包
        output_config = {
             "translated_suffix": self.config.output_filename_suffix,
             "bilingual_suffix": "_bilingual",
             "bilingual_order": self.config.bilingual_text_order,
             "source_lang_code": self._resolve_output_source_language(self.config.source_language),
             "target_lang_code": self._resolve_output_target_language(self.config.target_language),
        }

        # 写入文件
        self._assert_game_output_scope(scope,task_scope=task_scope)
        self.file_writer.output_translated_content(
            execution_project if scope is not None else self.cache_manager.project,
            checked_output if scope is not None else self.config.label_output_path,
            self.config.label_input_path,
            output_config,
        )
        self.print("")
        self.info(f"翻译结果已保存至 {self.config.label_output_path} 目录 ...")
        self.print("")

        # Finish game reports before UI listeners can adopt another project.
        if scope is not None and self.translation_result_check.is_enabled(self.config):
            self.translation_result_check.check_cache(self.config,execution_project,output_path=checked_output)

        # 重置内部状态（正常完成翻译）
        Base.work_status = Base.STATUS.TASKSTOPPED

        # 触发翻译停止完成的事件
        completion={'game_project_root':scope[1],'project_id':scope[2]} if scope is not None else {}
        self._emit_game_task_event(task_scope,Base.EVENT.TASK_STOP_DONE, completion)

        if scope is None and self.translation_result_check.is_enabled(self.config):
            self.translation_result_check.check_cache(self.config, self.cache_manager.project)


        # 触发翻译完成事件
        self._emit_game_task_event(task_scope,Base.EVENT.TASK_COMPLETED, completion)

    # 润色主流程
    def _polish_start_impl(self, continue_status: bool,*,task_scope=None,expected_project=None) -> None:

        # 设置翻译状态为正在翻译状态
        if task_scope is None:Base.work_status = Base.STATUS.TASKING

        # 读取配置文件，并保存到该类中
        self.config.initialize("polish")

        # 配置当前激活接口信息
        self.config.prepare_for_active_platform("polish")

        execution_project=self.cache_manager.project
        checked_output=self._preflight_task_output(getattr(self.config,'label_polish_output_path',None),task_scope=task_scope)
        scope=(execution_project,execution_project.get_extra('game_project_root'),execution_project.project_id) if checked_output is not None else None
        self.config.load_project_table_data(self.cache_manager)
        if expected_project is not None and self.cache_manager.project is not expected_project:
            raise ValueError('TASK_START_PROJECT_CHANGED')

        # 配置请求限制器
        self.request_limiter.set_limit(self.config.rpm_limit)

        # 初开始任务时，生成监控数据
        if continue_status == False:
            self.project_status_data = CacheProjectStatistics()
            self.cache_manager.project.stats_data = self.project_status_data
        # 继续翻译时加载存储的监控数据
        else:
            self.project_status_data = self.cache_manager.project.stats_data
            self.project_status_data.start_time = time.time() # 重置开始时间
            self.project_status_data.total_completion_tokens = 0 # 重置完成的token数量                  

        # 更新监控面板信息
        self._sync_game_progress(task_scope,continue_status)
        self._emit_game_task_event(task_scope,Base.EVENT.TASK_UPDATE, self.project_status_data.to_dict())

        # 文本过滤
        self.text_filter.filter_project(self.config, self.cache_manager.project)


        # 根据最大轮次循环
        round_limit=min(self.config.round_limit,3) if task_scope is not None else self.config.round_limit
        for current_round in range(round_limit + 1):
            self._assert_game_output_scope(scope,task_scope=task_scope)
            # 检测是否需要停止任务
            if Base.work_status == Base.STATUS.STOPING:
                # 循环次数比实际最大轮次要多一轮，当触发停止翻译的事件时，最后都会从这里退出任务
                # 执行到这里说明停止任意的任务已经执行完毕，可以重置内部状态了
                Base.work_status = Base.STATUS.TASKSTOPPED
                return None

            # 获取待润色的条目数量
            item_count_status_unpolishd = self.cache_manager.get_item_count_by_status(TranslationStatus.TRANSLATED)

            # 判断是否需要继续润色
            if item_count_status_unpolishd == 0:
                self.print("")
                self.info("所有文本均已润色，润色任务已结束 ...")
                self.print("")
                break

            # 达到最大任务轮次时
            if item_count_status_unpolishd > 0 and current_round == round_limit:
                self.print("")
                self.warning("已达到最大任务轮次，仍有部分文本未润色，请检查结果 ...")
                self.print("")
                break

            # 第一轮时且不是继续润色时，记录总行数
            if current_round == 0 and continue_status == False:
             self.project_status_data.total_line = item_count_status_unpolishd

            # 第二轮开始对半切分
            if current_round > 0:
                self.config.lines_limit = max(1, int(self.config.lines_limit / 2))
                self.config.tokens_limit = max(1, int(self.config.tokens_limit / 2))

            # 生成缓存数据条目片段的合集列表
            chunks, previous_chunks, file_paths = self.cache_manager.generate_item_chunks(
                "line" if self.config.tokens_limit_switch == False else "token",
                self.config.lines_limit if self.config.tokens_limit_switch == False else self.config.tokens_limit,
                getattr(self.config, "polishing_pre_line_counts", 10),
                TaskType.POLISH
            )

            # 生成润色任务合集列表
            tasks_list = []
            if Base.work_status == Base.STATUS.STOPING:
                Base.work_status = Base.STATUS.TASKSTOPPED
                return None
            game_preparation = None
            if chunks and self.cache_manager.project.get_extra('game_project_root'):
                from ModuleFolders.Service.GameProject.GameBatchPreparation import GameBatchPreparation
                game_preparation = GameBatchPreparation(self.cache_manager.project.get_extra('game_project_root'))
            print("")
            self.info(f"正在生成润色任务 ...")
            for chunk, previous_chunk, file_path in tqdm(zip(chunks, previous_chunks, file_paths),desc="生成润色任务", total=len(chunks)):
                if Base.work_status == Base.STATUS.STOPING:
                    break

                task = PolisherTask(self.config, self.request_limiter)  # 实例化
                task.set_items(chunk)  # 传入该任务待润色文
                self._bind_task_execution(task,task_scope)
                task.set_previous_items(previous_chunk)  # 传入该任务待润色文的上文
                if game_preparation is not None:
                    task.prepare(game_preparation=game_preparation)
                else:
                    task.prepare()  # 预先构建消息列表
                tasks_list.append(task)
            GlossaryHelper.clear_cache()
            if Base.work_status == Base.STATUS.STOPING:
                Base.work_status = Base.STATUS.TASKSTOPPED
                return None
            self.info(f"已经生成全部润色任务 ...")
            self.print("")

            # 输出开始润色的日志
            self.print("")
            self.info(f"当前轮次 - {current_round + 1}")
            self.info(f"最大轮次 - {round_limit}")
            self.info(f"项目类型 - {self.config.translation_project}")
            self.print("")
            self.info(f"接口名称 - {self.config.platforms.get(self.config.target_platform, {}).get('name', '未知')}")
            self.info(f"接口地址 - {self.config.base_url}")
            self.info(f"模型名称 - {self.config.model}")
            self.print("")
            self.info(f"RPM 限额 - {self.config.rpm_limit}")

            # 根据提示词规则打印基础指令
            system = ""
            if self.config.polishing_prompt_selection["last_selected_id"] == PromptBuilderEnum.POLISH_COMMON:
                system = PromptBuilderPolishing.build_system(self.config)
            else:
                system = self.config.polishing_prompt_selection["prompt_content"]
            self.print("")
            if system:
                self.info(f"本次任务使用以下基础提示词：\n{system}\n") 

            self.info(f"即将开始执行润色任务，预计任务总数为 {len(tasks_list)}, 同时执行的任务数量为 {self.config.actual_thread_counts}，请注意保持网络通畅 ...")
            time.sleep(3)
            self.print("")

            # 开始执行润色务,构建异步线程池
            executor = concurrent.futures.ThreadPoolExecutor(max_workers = self.config.actual_thread_counts, thread_name_prefix = "polisher")
            self._set_active_executor(executor)
            try:
                for task in tasks_list:
                    if Base.work_status == Base.STATUS.STOPING:
                        break

                    try:
                        future = executor.submit(task.start)
                    except RuntimeError:
                        if Base.work_status == Base.STATUS.STOPING:
                            break
                        raise

                    future.add_done_callback(partial(self.task_done_callback,task_scope=task_scope,stats=self.project_status_data))  # 为future对象添加一个回调函数，当任务完成时会被调用，更新数据
            finally:
                try:
                    executor.shutdown(wait=True, cancel_futures=Base.work_status == Base.STATUS.STOPING)
                finally:
                    self._clear_active_executor(executor)

        # 等待可能存在的缓存文件写入请求处理完毕
        time.sleep(CacheManager.SAVE_INTERVAL)

        # 输出配置包
        output_config = {
             "translated_suffix": self.config.output_filename_suffix,
             "bilingual_suffix": "_bilingual",
             "bilingual_order": self.config.bilingual_text_order,
             "source_lang_code": self._resolve_output_source_language(self.config.source_language),
             "target_lang_code": self._resolve_output_target_language(self.config.target_language),
        }

        # 写入文件
        self._assert_game_output_scope(scope,task_scope=task_scope)
        self.file_writer.output_translated_content(
            execution_project if scope is not None else self.cache_manager.project,
            checked_output if scope is not None else self.config.label_polish_output_path,
            self.config.label_input_path,
            output_config,
        )
        self.print("")
        self.info(f"润色结果已保存至 {self.config.label_polish_output_path} 目录 ...")
        self.print("")

        if scope is not None and self.translation_result_check.is_enabled(self.config):
            self.translation_result_check.check_cache(self.config,execution_project,output_path=checked_output)

        # 重置内部状态
        Base.work_status = Base.STATUS.TASKSTOPPED

        # 触发事件
        completion={'game_project_root':scope[1],'project_id':scope[2]} if scope is not None else {}
        self._emit_game_task_event(task_scope,Base.EVENT.TASK_STOP_DONE, completion)     # 翻译停止完成的事件
        self._emit_game_task_event(task_scope,Base.EVENT.TASK_COMPLETED, completion)     # 翻译完成事件



    # 单个翻译任务完成时,更新项目进度状态   
    def task_done_callback(self, future: concurrent.futures.Future,*,task_scope=None,stats=None) -> None:
        try:
            # 获取结果
            result = future.result()

            # 结果为空则跳过后续的更新步骤
            if result == None or len(result) == 0:
                return

            if task_scope is not None:
                from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for
                coordinator=coordinator_for(self.cache_manager)
                coordinator.assert_owner(task_scope,self.cache_manager.project)
                if not coordinator.owns_job(task_scope,result.get('job_id')):return
            captured_stats=stats if stats is not None else self.project_status_data

            # 更新翻译进度到缓存数据
            with captured_stats.atomic_scope():
                captured_stats.total_requests += 1
                captured_stats.error_requests += 0 if result.get("check_result") else 1
                captured_stats.line += result.get("row_count", 0)
                captured_stats.token += result.get("prompt_tokens", 0) + result.get("completion_tokens", 0)
                captured_stats.total_completion_tokens += result.get("completion_tokens", 0)
                captured_stats.time = time.time() - captured_stats.start_time
                stats_dict = captured_stats.to_dict()

            # 请求保存缓存文件
            self.cache_manager.require_save_to_file()

            # 触发翻译进度更新事件
            if task_scope is not None:stats_dict['job_id']=result['job_id']
            self._emit_game_task_event(task_scope,Base.EVENT.TASK_UPDATE,stats_dict)
        except concurrent.futures.CancelledError:
            return
        except Exception as e:
            self.error(f"翻译任务错误 ... {e}", e)
