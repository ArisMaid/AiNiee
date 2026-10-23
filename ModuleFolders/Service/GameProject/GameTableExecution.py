"""One captured table selection, shared preparation and concurrent request jobs."""
from concurrent.futures import ThreadPoolExecutor,wait,CancelledError
import time,threading,json
from ModuleFolders.Base.Base import Base
from ModuleFolders.Service.Cache.CacheItem import TranslationStatus
from .GameTaskScope import coordinator_for,bind_game_job,release_game_job
from .GameBatchPreparation import GameBatchPreparation
from .GameBatchRunner import GameBatchRunner
from .GameSceneChunks import contiguous_scene_runs


def handle_table_start(owner,data,mode,target):
    """Validate queued admission before a worker thread or provider config."""
    from .GameCacheIdentity import is_game_projection
    from .GameTaskScope import has_game_scope
    manager=owner.cache_manager
    if not is_game_projection(getattr(manager,'project',None)) and not has_game_scope(data):
        current=getattr(manager,'_game_task_coordinator',None)
        if current is not None and current.active:
            owner.warning('游戏任务仍在执行，不能启动其他工程。');return True
        return False
    if manager is None:return True
    coordinator=coordinator_for(manager);scope=None
    try:
        scope=coordinator.accept(manager.project,data)
        if scope.operation!='table-'+mode:raise ValueError('GAME_TASK_OPERATION_INVALID')
        if coordinator.stop_requested(scope):raise ValueError('GAME_TABLE_CANCELLED')
        scope.validate_canonical(manager.project)
        threading.Thread(target=target,args=(data,),kwargs={'task_scope':scope},daemon=True).start()
    except Exception as error:
        owner.warning('游戏表格开始通知已拒绝：'+(str(error) or type(error).__name__))
        if scope is not None and coordinator.finish(scope):
            Base.work_status=Base.STATUS.TASKSTOPPED
            owner.emit(Base.EVENT.TASK_STOP_DONE,{**scope.payload(),'error':str(error) or type(error).__name__})
    return True


def _completed(futures):
    # shutdown(cancel_futures=True) may leave futures in CANCELLED rather than
    # CANCELLED_AND_NOTIFIED. Recheck done() after a bounded wait instead of
    # waiting forever for as_completed's waiter notification.
    pending=set(futures)
    while pending:
        ready={future for future in pending if future.done()}
        if not ready:
            wait(pending,timeout=.05)
            continue
        pending.difference_update(ready)
        yield from ready


def _selections(project,data,mode):
    key='items_to_'+mode if mode in ('polish','proofread') else 'items_to_translate'
    tasks=data.get('file_tasks')
    if tasks is None and mode=='proofread':tasks=data.get('proofread_jobs')
    if tasks is None:tasks=[data]
    if not isinstance(tasks,list) or not tasks:raise ValueError('GAME_TABLE_SELECTION_MISSING')
    selections={};hints={}
    for task in tasks:
        if not isinstance(task,dict):raise ValueError('GAME_TABLE_SELECTION_INVALID')
        path=task.get('file_path')
        if not isinstance(path,str) or not path:raise ValueError('GAME_TABLE_FILE_NOT_FOUND')
        cache_file=project.get_file(path)
        if cache_file is None:raise ValueError(f'GAME_TABLE_FILE_NOT_FOUND: {path}')
        rows=task.get(key)
        if not isinstance(rows,list):raise ValueError(f'GAME_TABLE_SELECTION_MISSING: {key}')
        available={item.text_index for item in cache_file.items}
        indexes=selections.setdefault(path,set())
        for row in rows:
            if not isinstance(row,dict) or 'text_index' not in row:raise ValueError('GAME_TABLE_SELECTION_MISSING_TEXT_INDEX')
            index=row['text_index']
            if type(index) is not int:raise ValueError('GAME_TABLE_SELECTION_INVALID_TEXT_INDEX')
            if index not in available:raise ValueError(f'GAME_TABLE_SELECTION_UNKNOWN: {index}')
            indexes.add(index)
            if mode=='proofread':
                if row.get('target_field','translated_text')!='translated_text':raise ValueError('GAME_PROOFREAD_TARGET_FIELD_INVALID')
                hint=row.get('error_type','')
                if not isinstance(hint,str):raise ValueError('GAME_PROOFREAD_HINT_INVALID')
                hints[(path,index)]=hint[:500]
    selected={};runs=[];seen=set()
    for path,indexes in selections.items():
        selected[path]=[]
        for run in contiguous_scene_runs(project.get_file(path).items):
            chosen=[]
            for item in run:
                uid=item.get_extra('unit_id')
                if item.text_index in indexes and uid not in seen:
                    seen.add(uid);chosen.append(item);selected[path].append(item)
            if chosen:runs.append((path,chosen))
    return selected,runs,{item.get_extra('unit_id'):hints.get((path,item.text_index),'')
        for path,items in selected.items() for item in items}


def _run_batch(manager,scope,batch,requester,check_active):
    """One request plus at most two retries, retaining original CAS and markers."""
    jobs=[];prompt=completion=failed=accepted=0;last_error='';result={}
    requested=len(batch.units)
    def bind(info):
        bind_game_job(manager,scope,info);jobs.append(info['job_id'])
    for attempt in range(3):
        retry_ids=[];last_error='';jobs_before=len(jobs)
        try:
            check_active()
            result=batch.run(requester,on_job=bind,
                on_job_done=lambda info:release_game_job(manager,scope,info))
            accepted+=result.get('row_count',0)
            retry_ids=result.get('retry_unit_ids',[])
        except Exception as error:
            last_error=str(error) or type(error).__name__
            if isinstance(error,(json.JSONDecodeError,TimeoutError)) or last_error.startswith(
                    ('MODEL_REQUEST_FAILED','MODEL_EMPTY_RESPONSE','DUPLICATE_RESPONSE_ID','RESPONSE_ID_MISMATCH')):
                retry_ids=[u.unit_id for u in batch.units]
            result={'check_result':False,'row_count':0}
        if len(jobs)>jobs_before:
            from .ProjectStore import ProjectStore
            with ProjectStore(scope.root) as store:audited=store.get_job(jobs[-1])['result']
            prompt+=audited.get('prompt_tokens',0);completion+=audited.get('completion_tokens',0)
        if accepted==requested:break
        failed+=1
        if attempt==2 or result.get('cancelled') or not retry_ids or coordinator_for(manager).stop_requested(scope):break
        batch=batch.retry_subset(retry_ids)
    return {**result,'check_result':accepted==requested,'row_count':accepted,
        'job_id':jobs[-1] if jobs else None,'prompt_tokens':prompt,'completion_tokens':completion,
        'request_count':len(jobs),'failed_requests':failed,'error':last_error}


def run_table_group(owner,data,mode,*,config=None,requester=None,task_scope=None,config_factory=None):
    manager=owner.cache_manager;project=manager.project;coordinator=coordinator_for(manager)
    scope=task_scope;error='';count=0;selected={};counts={};errors={};initial_paths=[]
    tasks=data.get('file_tasks')
    if tasks is None and mode=='proofread':tasks=data.get('proofread_jobs')
    if isinstance(tasks,list):initial_paths=[task.get('file_path') for task in tasks if isinstance(task,dict)]
    else:initial_paths=[data.get('file_path')]
    try:
        if scope is None:
            if Base.work_status==Base.STATUS.STOPING:raise ValueError('GAME_TABLE_CANCELLED')
            scope=coordinator.reserve_current(manager,'table-'+mode,
                on_claim=lambda:setattr(Base,'work_status',Base.STATUS.TABLE_TASK))
            coordinator.accept(project,scope.payload())
        coordinator.assert_owner(scope,manager.project)
        if scope.operation!='table-'+mode:raise ValueError('GAME_TASK_OPERATION_INVALID')
        if coordinator.stop_requested(scope):raise ValueError('GAME_TABLE_CANCELLED')
        scope.validate_canonical(manager.project)
        selected,runs,hints=_selections(project,data,mode)
        counts={path:0 for path in selected};errors={path:[] for path in selected}
        if config is None:
            config=config_factory();config.initialize(mode);config.prepare_for_active_platform(mode)
        max_threads=getattr(config,'actual_thread_counts',1)
        if type(max_threads) is not int or max_threads<1:raise ValueError('GAME_TABLE_CONCURRENCY_INVALID')
        limiter=None
        if requester is None:
            from ModuleFolders.Infrastructure.RequestLimiter.RequestLimiter import RequestLimiter
            limiter=RequestLimiter();limiter.set_limit(max(1,getattr(config,'rpm_limit',60)))
        def check_active():
            coordinator.assert_owner(scope,manager.project)
            if coordinator.stop_requested(scope) or Base.work_status==Base.STATUS.STOPING:
                raise ValueError('GAME_TABLE_CANCELLED')
        check_active()
        preparation=GameBatchPreparation(scope.root) if runs else None
        batches=[]
        batch_size=1 if mode=='proofread' else 20
        for path,run in runs:
            for start in range(0,len(run),batch_size):
                check_active()
                batch=GameBatchRunner(run[start:start+batch_size],config,limiter,mode,
                    preparation=preparation,execution_scope=scope,issue_hints=hints)
                if batch.units:batches.append((path,batch))
        stats={'line':0,'total_line':sum(len(batch.units) for _,batch in batches),
            'start_time':time.time(),'token':0,'total_completion_tokens':0,'total_requests':0,'error_requests':0}
        def emit_progress(job_id=None):
            coordinator.assert_owner(scope,manager.project)
            owner.emit(Base.EVENT.TASK_UPDATE,{**stats,**scope.payload(job_id=job_id),
                'game_progress_revision':stats['total_requests']})
        emit_progress()
        def execute(batch):
            check_active()
            return _run_batch(manager,scope,batch,requester,check_active)
        with ThreadPoolExecutor(max_workers=max_threads,thread_name_prefix='translator-table') as pool:
            coordinator.register_canceller(scope,manager.project,lambda:pool.shutdown(wait=False,cancel_futures=True))
            futures={}
            for path,batch in batches:
                if coordinator.stop_requested(scope):break
                futures[pool.submit(execute,batch)]=path
            for future in _completed(futures):
                path=futures[future];job_id=None;failed=False;result={}
                try:
                    result=future.result();job_id=result.get('job_id')
                    if not coordinator.owns_job(scope,job_id):raise ValueError('GAME_TABLE_REQUEST_NOT_OWNED')
                    counts[path]+=result['row_count'];count+=result['row_count']
                    stats['line']=count
                    stats['token']+=result.get('prompt_tokens',0)+result.get('completion_tokens',0)
                    stats['total_completion_tokens']+=result.get('completion_tokens',0)
                    if not result.get('check_result'):raise ValueError(result.get('error') or 'GAME_TABLE_BATCH_INCOMPLETE')
                except CancelledError:
                    errors[path].append('GAME_TABLE_CANCELLED')
                    continue  # no request/job was started for this queued future
                except Exception as exc:errors[path].append(str(exc) or type(exc).__name__);failed=True
                stats['total_requests']+=max(1,result.get('request_count',1))
                stats['error_requests']+=max(int(failed),result.get('failed_requests',0))
                emit_progress(job_id if coordinator.owns_job(scope,job_id) else None)
        if coordinator.stop_requested(scope):error='GAME_TABLE_CANCELLED'
        failures=[message for messages in errors.values() for message in messages]
        if failures:error=error or failures[0]
    except Exception as exc:error=str(exc) or type(exc).__name__
    finally:
        if error:owner.warning('游戏表格任务未完成：'+error)
        try:
            if scope is not None:coordinator.assert_owner(scope,manager.project)
            for path in dict.fromkeys(initial_paths):
                items=selected.get(path,[])
                updated={item.text_index:item.translated_text for item in items if item.translated_text}
                packet=scope.payload() if scope is not None else {}
                if updated:
                    owner.emit(data.get('update_event',Base.EVENT.TABLE_BASIC_UPDATE),{**packet,'file_path':path,
                        'target_column_index':2,'translation_status':TranslationStatus.TRANSLATED if mode=='translate' else TranslationStatus.POLISHED,
                        'updated_items':updated})
                if data.get('done_event') is not None and mode!='proofread':
                    owner.emit(data['done_event'],{**packet,'file_path':path,'operation':mode,
                        'status':'error' if error else 'success' if counts.get(path,0) else 'empty',
                        'message':error,'updated_item_count':counts.get(path,0)})
            if mode=='proofread' and data.get('done_event') is not None:
                owner.emit(data['done_event'],{**(scope.payload() if scope is not None else {}),
                    'operation':'proofread','status':'error' if error else 'success' if count else 'empty',
                    'message':error,'updated_item_count':count,'updated_file_count':sum(value>0 for value in counts.values())})
        except Exception as exc:
            error=error or str(exc)
        finally:
            if scope is not None and coordinator.finish(scope):
                Base.work_status=Base.STATUS.TASKSTOPPED if scope.ui_owned else Base.STATUS.IDLE
                owner.emit(Base.EVENT.TASK_STOP_DONE,{**scope.payload(),'error':error})
    return {'row_count':count,'error':error}
