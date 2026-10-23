"""One local game execution and its queued events; request jobs remain separate.

Scopes belong to a CacheManager, never to serialized cache extras. Their UUID is
a UI execution identity, not a database job ID or evidence of accepted text.
"""
from dataclasses import dataclass,field
import threading
import uuid
from .GameCacheIdentity import game_project_root,game_root_key,is_game_projection,validate_game_project

_INIT_LOCK=threading.Lock()
_ACTIVE={'reserved','running','stopping'}
_OPERATIONS={'translate','polish','table-translate','table-polish','table-proofread','analysis'}


@dataclass(frozen=True,eq=False)
class GameTaskScope:
    project: object=field(repr=False)
    root: str
    project_id: str
    dataset_revision: int
    operation: str
    execution_id: str=field(default_factory=lambda:uuid.uuid4().hex)
    ui_owned: bool=False

    @classmethod
    def capture(cls,project,operation,*,ui_owned=False):
        if not isinstance(operation,str) or operation not in _OPERATIONS:raise ValueError('GAME_TASK_OPERATION_INVALID')
        if type(ui_owned) is not bool:raise ValueError('GAME_TASK_OWNER_INVALID')
        root=game_project_root(project)
        project_id=getattr(project,'project_id',None)
        dataset=project.get_extra('game_dataset_revision')
        if not isinstance(project_id,str) or not project_id or type(dataset) is not int or dataset<0:
            raise ValueError('GAME_TASK_PROJECTION_REFRESH_REQUIRED: 请重新载入游戏工程。')
        return cls(project,str(root),project_id,dataset,operation,ui_owned=ui_owned)

    def payload(self,*,job_id=None):
        result={'game_project_root':self.root,'project_id':self.project_id,
            'dataset_revision':self.dataset_revision,'game_execution_id':self.execution_id}
        if job_id is not None:
            if not isinstance(job_id,str) or not job_id:raise ValueError('GAME_TASK_JOB_INVALID')
            result['job_id']=job_id
        return result

    def assert_project(self,project):
        if project is not self.project:raise ValueError('GAME_TASK_PROJECT_CHANGED')
        if (game_root_key(game_project_root(project))!=game_root_key(self.root)
                or project.project_id!=self.project_id
                or type(project.get_extra('game_dataset_revision')) is not int
                or project.get_extra('game_dataset_revision')!=self.dataset_revision):
            raise ValueError('GAME_TASK_PROJECT_CHANGED')

    def validate_canonical(self,project,*,check_items=True,job_id=None):
        self.assert_project(project)
        from .ProjectStore import ProjectStore
        with ProjectStore(self.root) as store:
            store._connection.execute('BEGIN')
            try:
                validate_game_project(project,items=project.items_iter() if check_items else (),store=store)
                if store.metadata()['dataset_revision']!=self.dataset_revision:
                    raise ValueError('DATASET_REVISION_CONFLICT: 请重新载入游戏工程。')
                if job_id is not None:
                    if not isinstance(job_id,str) or not job_id:raise ValueError('GAME_TASK_JOB_CONTEXT_INVALID')
                    job=store.get_job(job_id)
                    role=self.operation.split('-')[-1]
                    operation={'translate':'TRANSLATE','analysis':'ANALYSIS'}.get(role,'POLISH')
                    if (job is None or job['operation']!=operation
                            or job['run_state'] not in {'RUNNING','CANCEL_REQUESTED','CANCELLED'}
                            or not self.matches(project,job['payload'])
                            or (role in ('proofread','analysis') and job['payload'].get('request_mode')!=role)
                            or ('request_mode' in job['payload'] and job['payload']['request_mode']!=role)):
                        raise ValueError('GAME_TASK_JOB_CONTEXT_INVALID')
            finally:store._connection.rollback()

    def matches(self,project,data,*,terminal=False):
        if not isinstance(data,dict):return False
        if project is not self.project:return False
        if not terminal:
            try:self.assert_project(project)
            except (ValueError,OSError):return False
        try:
            return (game_root_key(data.get('game_project_root'))==game_root_key(self.root)
                and data.get('project_id')==self.project_id
                and type(data.get('dataset_revision')) is int
                and data['dataset_revision']==self.dataset_revision
                and data.get('game_execution_id')==self.execution_id)
        except ValueError:return False


class GameTaskCoordinator:
    """Serialize admission and retain terminal identity for queued UI delivery."""
    def __init__(self):
        self._lock=threading.RLock()
        self._scope=None
        self._state='idle'
        self._consumed=False
        self._accepted=False
        self._jobs=set()
        self._active_jobs=set()
        self._cancel_pending=None

    @property
    def current(self):
        with self._lock:return self._scope

    @property
    def active(self):
        with self._lock:return self._state in _ACTIVE

    def reserve(self,project,operation,*,on_claim=None,ui_owned=False):
        with self._lock:
            if self._state in _ACTIVE:raise ValueError('GAME_TASK_ALREADY_ACTIVE')
            if self._completion_pending():raise ValueError('GAME_TASK_COMPLETION_PENDING')
            scope=GameTaskScope.capture(project,operation,ui_owned=ui_owned)
            if on_claim is not None:on_claim()
            self._scope=scope;self._state='reserved';self._consumed=False;self._jobs=set();self._active_jobs=set()
            self._cancel_pending=None
            self._accepted=False
            return scope

    def reserve_current(self,manager,operation,*,on_claim=None,ui_owned=False):
        with self._lock:return self.reserve(manager.project,operation,on_claim=on_claim,ui_owned=ui_owned)

    def _completion_pending(self):
        return self._state=='terminal' and self._scope is not None and self._scope.ui_owned and not self._consumed

    def assert_can_adopt(self):
        with self._lock:
            if self._state in _ACTIVE or self._completion_pending():
                raise ValueError('GAME_TASK_PROJECT_SWITCH_BLOCKED: 请先停止当前任务并等待界面完成。')

    def adopt(self,action):
        with self._lock:
            self.assert_can_adopt()
            action()

    def accept(self,project,data):
        with self._lock:
            scope=self._scope
            if (self._state not in {'reserved','stopping'} or self._accepted
                    or scope is None or not scope.matches(project,data)):
                raise ValueError('GAME_TASK_START_CONTEXT_INVALID')
            self._accepted=True
            if self._state=='reserved':self._state='running'
            return scope

    def assert_owner(self,scope,project,*,allow_terminal=False):
        with self._lock:
            if self._scope is not scope or (self._state not in _ACTIVE and not allow_terminal):
                raise ValueError('GAME_TASK_EXECUTION_CHANGED')
            scope.assert_project(project)

    def request_stop(self,project,data):
        with self._lock:
            if self._state not in _ACTIVE or self._scope is None or not self._scope.matches(project,data):return False
            self._state='stopping'
            return True

    def stop_requested(self,scope):
        with self._lock:return self._scope is scope and self._state=='stopping'

    def stop_current(self):
        """Application shutdown controls its own execution, not an event's scope."""
        with self._lock:
            if self._state not in _ACTIVE:return None
            self._state='stopping'
            return self._scope

    def run_if_active(self,scope,action):
        """Serialize a short control action with finish/new admission."""
        with self._lock:
            if self._scope is not scope or self._state not in _ACTIVE:return False
            action()
            return True

    def finish(self,scope):
        with self._lock:
            if self._scope is not scope or self._state not in _ACTIVE:return False
            self._state='terminal'
            self._cancel_pending=None
            return True

    def register_canceller(self,scope,project,action):
        """Own a pending-future canceller; a stop racing registration still wins."""
        with self._lock:
            self.assert_owner(scope,project)
            self._cancel_pending=action
            if self._state=='stopping':action()

    def cancel_pending(self,scope):
        with self._lock:
            if self._scope is scope and self._state in _ACTIVE and self._cancel_pending is not None:
                self._cancel_pending()

    def event_matches(self,project,data):
        with self._lock:
            return (self._scope is not None and self._scope.matches(project,data)
                and ('job_id' not in data or self.owns_job(self._scope,data['job_id'])))

    def consume_done(self,project,data):
        with self._lock:
            if (self._state!='terminal' or self._consumed or self._scope is None
                    or not self._scope.matches(project,data,terminal=True)
                    or ('job_id' in data and not self.owns_job(self._scope,data['job_id']))):return False
            # The owning failed execution may release its own UI even if cache
            # metadata was damaged. It cannot authorize another write afterward.
            try:self._scope.assert_project(project)
            except (ValueError,OSError):project.set_extra('game_projection_refresh_required',True)
            self._consumed=True
            return True

    def bind_job(self,scope,project,info):
        """Called only after the runner has created its real job and lease."""
        with self._lock:
            self.assert_owner(scope,project)
            if self._state!='running':raise ValueError('GAME_TASK_STOP_REQUESTED')
            if not scope.matches(project,info):raise ValueError('GAME_TASK_JOB_CONTEXT_INVALID')
            job_id=info.get('job_id')
            if not isinstance(job_id,str) or not job_id:raise ValueError('GAME_TASK_JOB_INVALID')
            self._jobs.add(job_id)
            self._active_jobs.add(job_id)

    def release_job(self,scope,job_id):
        with self._lock:
            if self._scope is scope:self._active_jobs.discard(job_id)

    def active_job_ids(self,scope):
        with self._lock:
            return tuple(sorted(self._active_jobs)) if self._scope is scope else ()

    def owns_job(self,scope,job_id):
        with self._lock:return self._scope is scope and isinstance(job_id,str) and job_id in self._jobs

    def job_ids(self,scope):
        with self._lock:
            if self._scope is not scope:return ()
            return tuple(sorted(self._jobs))


def coordinator_for(manager):
    # Only allocation is global-lock protected; there is no global project map.
    with _INIT_LOCK:
        coordinator=getattr(manager,'_game_task_coordinator',None)
        if coordinator is None:
            coordinator=GameTaskCoordinator();manager._game_task_coordinator=coordinator
        return coordinator


def bind_game_job(manager,scope,info):
    from .ProjectStore import ProjectStore
    from .JobControl import request_action,JobCancelled
    coordinator=coordinator_for(manager)
    coordinator.assert_owner(scope,manager.project)
    scope.validate_canonical(manager.project,check_items=False,job_id=info.get('job_id'))
    try:coordinator.bind_job(scope,manager.project,info)
    except ValueError as error:
        if str(error)!='GAME_TASK_STOP_REQUESTED':raise
        with ProjectStore(scope.root) as store:request_action(store,info['job_id'],'cancel')
        raise JobCancelled(info['job_id']) from error


def release_game_job(manager,scope,info):
    coordinator_for(manager).release_job(scope,info['job_id'])


def has_game_scope(data):
    return isinstance(data,dict) and any(key in data for key in ('game_project_root','game_execution_id'))


def game_task_progress(project,operation):
    """Count canonical-projection scheduling work for this role, without I/O."""
    if operation not in ('translate','polish'):raise ValueError('GAME_TASK_OPERATION_INVALID')
    from ModuleFolders.Service.Cache.CacheItem import TranslationStatus
    pending_status=TranslationStatus.UNTRANSLATED if operation=='translate' else TranslationStatus.TRANSLATED
    completed_statuses=({TranslationStatus.TRANSLATED,TranslationStatus.POLISHED}
        if operation=='translate' else {TranslationStatus.POLISHED})
    pending=completed=0
    for item in project.items_iter():
        if item.translation_status==pending_status:pending+=1
        elif item.translation_status in completed_statuses:completed+=1
    return {'pending':pending,'completed':completed,'total':pending+completed}


def event_matches_current(manager,data,*,consume_done=False):
    project=getattr(manager,'project',None)
    if not is_game_projection(project):return not has_game_scope(data)
    coordinator=getattr(manager,'_game_task_coordinator',None)
    if coordinator is None:return False
    return (coordinator.consume_done(project,data) if consume_done else coordinator.event_matches(project,data))
