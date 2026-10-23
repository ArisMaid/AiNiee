"""Reuse the two-stage analyzer with one canonical game execution/job."""
import os,threading
from .GameTaskScope import coordinator_for,bind_game_job,release_game_job
from .ProjectStore import ProjectStore
from .ProjectLock import ProjectLock,JobLease
from .JobControl import JobControl,JobCancelled


class GameAnalysisSession:
    def __init__(self,owner,scope,requester=None):
        self.owner=owner;self.manager=owner.cache_manager;self.scope=scope
        self.coordinator=coordinator_for(self.manager);self.requester=requester
        self.job_id=None;self.lease=None;self.data=None
        self.attempts=self.valid_responses=self.exhausted_groups=0
        self._lock=threading.Lock()

    def check(self):
        self.coordinator.assert_owner(self.scope,self.manager.project)
        if self.coordinator.stop_requested(self.scope):raise JobCancelled(self.job_id or 'analysis')
        self.scope.validate_canonical(self.manager.project,check_items=False)
        if self.job_id:
            with ProjectStore(self.scope.root) as store:JobControl(store,self.job_id).check(force=True)

    def start(self):
        self.check()
        with ProjectLock(self.scope.root),ProjectStore(self.scope.root) as store:
            store._connection.execute('BEGIN')
            try:
                self.units=store.units();meta=store.metadata();self.record=store.analysis_record()
                if meta['dataset_revision']!=self.scope.dataset_revision:raise ValueError('DATASET_REVISION_CONFLICT')
            finally:store._connection.rollback()
            job=store.create_job('ANALYSIS',{**self.scope.payload(),'request_mode':'analysis',
                'analysis_revision':self.record['revision']})
            self.job_id=job['job_id'];store.update_job(self.job_id,run_state='RUNNING',stage='prepare')
            self.lease=JobLease(self.scope.root,self.job_id);self.lease.__enter__()
        bind_game_job(self.manager,self.scope,self.scope.payload(job_id=self.job_id))

    def chunks(self,limit):
        from ModuleFolders.Infrastructure.Tokener.Tokener import Tokener
        self.check();chunks=[];current=[];tokens=0;previous=None;tokener=Tokener()
        for unit in self.units:
            if not unit.source_text.strip():continue
            key=unit.occurrences[0].relative_path if unit.occurrences else ''
            count=tokener.num_tokens_from_str(unit.source_text)
            if current and (key!=previous or tokens+count>limit):
                chunks.append(current);current=[];tokens=0
            current.append({'unit_id':unit.unit_id,'source_text':unit.source_text})
            tokens+=count;previous=key
        if current:chunks.append(current)
        self.check();return chunks

    def register_pool(self,pool):
        self.coordinator.register_canceller(self.scope,self.manager.project,
            lambda:pool.shutdown(wait=False,cancel_futures=True))

    def request(self,messages,system_prompt,config):
        self.check()
        if self.requester is None:
            if os.environ.get('AINIEE_OFFLINE')=='1':raise ValueError('OFFLINE_MODEL_DISABLED')
            from ModuleFolders.Infrastructure.LLMRequester.LLMRequester import LLMRequester
            requester=LLMRequester()
        else:requester=self.requester
        with self._lock:self.attempts+=1
        response=requester.sent_request([dict(m) for m in messages],system_prompt,
            config.get_active_platform_configuration('extract'))
        self.check();return response

    def event(self,event,data):
        self.owner.emit(event,{**data,**self.scope.payload(job_id=self.job_id)})

    def save(self,data):
        from .JobController import begin_commit
        self.check()
        if self.exhausted_groups and not self.valid_responses:raise ValueError('ANALYSIS_NO_VALID_RESPONSE: 保留原分析结果，请检查接口后重试。')
        if self.exhausted_groups:data={**data,'status':'partial'}
        with ProjectLock(self.scope.root),ProjectStore(self.scope.root) as store:
            store.update_job(self.job_id,result={'attempts':self.attempts,
                'valid_responses':self.valid_responses,'exhausted_groups':self.exhausted_groups})
            begin_commit(store,JobControl(store,self.job_id))
            record=store.save_analysis_data(data,project_id=self.scope.project_id,
                expected_dataset_revision=self.scope.dataset_revision,
                expected_revision=self.record['revision'],job_id=self.job_id)
        self.data=record['data']
        if self.manager.project is self.scope.project:
            self.scope.project.set_extra('analysis_v1',record['data'])
            self.scope.project.set_extra('game_analysis_revision',record['revision'])

    def close(self,error=None):
        try:
            if self.job_id and error is not None:
                with ProjectStore(self.scope.root) as store:JobControl(store,self.job_id).fail(error)
        finally:
            if self.lease is not None:self.lease.__exit__(None,None,None)
            if self.job_id:release_game_job(self.manager,self.scope,{'job_id':self.job_id})


def handle_analysis_start(owner,data):
    from ModuleFolders.Base.Base import Base
    from .GameCacheIdentity import is_game_projection
    from .GameTaskScope import has_game_scope
    manager=owner.cache_manager
    if not is_game_projection(manager.project) and not has_game_scope(data):
        coordinator=getattr(manager,'_game_task_coordinator',None)
        return bool(coordinator and coordinator.active)
    coordinator=coordinator_for(manager);scope=None
    try:
        scope=coordinator.accept(manager.project,data)
        if scope.operation!='analysis':raise ValueError('GAME_TASK_OPERATION_INVALID')
        scope.validate_canonical(manager.project)
        threading.Thread(target=owner.analysis_start_target,kwargs={'task_scope':scope},daemon=True).start()
    except Exception as error:
        owner.warning('游戏全文分析开始已拒绝：'+str(error))
        if scope is not None and coordinator.finish(scope):
            Base.work_status=Base.STATUS.TASKSTOPPED
            owner.emit(Base.EVENT.ANALYSIS_TASK_DONE,{**scope.payload(),'status':'error','message':str(error)})
    return True


def run_game_analysis(owner,*,task_scope=None,config=None,requester=None):
    from ModuleFolders.Base.Base import Base
    from ModuleFolders.Service.TaskExecutor.AnalysisTask import AnalysisTask
    coordinator=coordinator_for(owner.cache_manager);scope=task_scope;session=None;error=None
    status='error';message=''
    try:
        if scope is None:
            scope=coordinator.reserve_current(owner.cache_manager,'analysis',
                on_claim=lambda:setattr(Base,'work_status',Base.STATUS.ANALYSIS_TASK))
            coordinator.accept(owner.cache_manager.project,scope.payload())
        if scope.operation!='analysis':raise ValueError('GAME_TASK_OPERATION_INVALID')
        session=GameAnalysisSession(owner,scope,requester);session.start()
        task=AnalysisTask(owner.cache_manager,owner._set_active_executor,owner._clear_active_executor,
            game_session=session,config=config)
        task.run();status=session.data.get('status','success');message='全文分析完成，结果仅为术语候选，请确认后采用。'
    except Exception as caught:
        error=caught;status='stopped' if isinstance(caught,JobCancelled) or (scope and coordinator.stop_requested(scope)) else 'error'
        message=str(caught) or type(caught).__name__
    finally:
        if session is not None:
            try:session.close(error)
            except Exception as cleanup:
                status='error';message='分析收尾失败，请重新加载工程：'+str(cleanup)
        if scope is not None and coordinator.finish(scope):
            Base.work_status=Base.STATUS.TASKSTOPPED
            owner.emit(Base.EVENT.ANALYSIS_TASK_DONE,{**scope.payload(),
                'status':status,'message':message,'analysis_data':session.data if session else None})


def game_analysis_data(manager,*,data=None,expected_project=None):
    """Read canonical candidates or save one explicit view's manual edits."""
    from .GameCacheIdentity import game_project_root,validate_game_project
    project=manager.project
    if data is not None and expected_project is not project:raise ValueError('ANALYSIS_PROJECT_CHANGED: 请重新加载分析页。')
    with ProjectLock(game_project_root(project)),ProjectStore(game_project_root(project)) as store:
        validate_game_project(project,items=(),store=store)
        if data is None:record=store.analysis_record()
        else:
            record=store.save_analysis_data(data,project_id=project.project_id,
                expected_dataset_revision=project.get_extra('game_dataset_revision'),
                expected_revision=project.get_extra('game_analysis_revision'))
    project.set_extra('game_analysis_revision',record['revision'])
    result=record['data'] if record['dataset_revision']==project.get_extra('game_dataset_revision') else {}
    project.set_extra('analysis_v1',result)
    return result
