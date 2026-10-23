"""Capture table task groups before queueing and filter the bound page first."""
from ModuleFolders.Base.Base import Base
from ModuleFolders.Service.GameProject.GameCacheIdentity import is_game_projection
from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for,event_matches_current,has_game_scope


def table_event_matches(page,data):
    manager=page.cache_manager
    if manager is None:return not has_game_scope(data)
    bound=getattr(page,'_game_table_project',None)
    if is_game_projection(manager.project) or is_game_projection(bound):
        if bound is not manager.project:return False
    return event_matches_current(manager,data)


def submit_game_table(page,mode,file_tasks,update_event,done_event):
    manager=page.cache_manager
    if manager is None:return None
    bound=getattr(page,'_game_table_project',None)
    if not is_game_projection(manager.project) and not is_game_projection(bound):return None
    coordinator=coordinator_for(manager);scope=None
    try:
        if getattr(page,'_game_table_project',None) is not manager.project:
            raise ValueError('GAME_TABLE_VIEW_CHANGED: 请重新打开此表格。')
        key='items_to_'+mode if mode in ('polish','proofread') else 'items_to_translate'
        if not file_tasks or not any(task.get(key) for task in file_tasks):return False
        if Base.work_status!=Base.STATUS.IDLE:raise ValueError('请先停止当前任务。')
        scope=coordinator.reserve_current(manager,'table-'+mode,
            on_claim=lambda:setattr(Base,'work_status',Base.STATUS.TABLE_TASK),ui_owned=True)
        # Queue a detached selection. Edited source/destination cell text never
        # authorizes a request; the worker obtains text from canonical storage.
        tasks=[{'file_path':task['file_path'],key:[{'text_index':row['text_index']} for row in task[key]]}
            for task in file_tasks]
        if mode=='proofread':
            for original,task in zip(file_tasks,tasks,strict=True):
                for row,new in zip(original[key],task[key],strict=True):
                    hint=row.get('error_type','')
                    if not isinstance(hint,str):raise ValueError('GAME_PROOFREAD_HINT_INVALID')
                    new.update(error_type=hint[:500],target_field=row.get('target_field','translated_text'))
        event=(Base.EVENT.TABLE_PROOFREAD_START if mode=='proofread' else
            Base.EVENT.TABLE_POLISH_START if mode=='polish' else Base.EVENT.TABLE_TRANSLATE_START)
        page.emit(event,{**scope.payload(),'file_tasks':tasks,'update_event':update_event,'done_event':done_event})
        return True
    except Exception as error:
        if scope is not None and coordinator.finish(scope):
            if coordinator.consume_done(manager.project,scope.payload()):Base.work_status=Base.STATUS.IDLE
        page.warning_toast(page.tra('任务未开始'),str(error))
    return False
