"""AiNiee cache is a rebuildable projection, never the game project's authority."""
from .ProjectStore import ProjectStore
from .GameCacheIdentity import is_game_projection,game_project_root,validate_game_project


class ResetProjectionRefreshRequired(ValueError):
    """The reset transaction finished; only its disposable view needs recovery."""
    def __init__(self,changed_count):
        self.changed_count=changed_count
        outcome=(f'状态重置已保存（{changed_count} 项）' if changed_count else '状态重置检查已完成（没有更改）')
        super().__init__(f'GAME_PROJECT_REFRESH_REQUIRED: {outcome}；缓存视图刷新失败，请重新加载游戏工程。')


def _translation_state(unit,translation,policy):
    from ModuleFolders.Service.Cache.CacheItem import TranslationStatus
    valid=(translation.get('source_hash')==unit.source_hash
        and not translation.get('stale') and bool(translation.get('text')))
    text=translation.get('text','') if valid else ''
    status=(TranslationStatus.UNTRANSLATED if valid and translation.get('origin')=='reset-translate' else
        TranslationStatus.POLISHED if valid and translation.get('origin')=='polish' else
        TranslationStatus.TRANSLATED if valid else TranslationStatus.UNTRANSLATED)
    _,source_issues=policy.scan(unit.source_text,unit.unit_id)
    if translation.get('manual_locked') or source_issues:status=TranslationStatus.EXCLUDED
    return text,status,[issue.code for issue in source_issues]


def _selected_item(project,storage_path,text_index):
    try:
        file=project.get_file(storage_path) if project else None
        return file.get_item(text_index) if file is not None else None
    except (KeyError,IndexError,TypeError):return None


def _require_selected_item(item,text_index):
    if type(text_index) is not int or text_index<0 or item is None:
        raise ValueError('GAME_CACHE_ITEM_INVALID: reload the project')
    return item


def build_projection(store, *, check=None):
    if check is not None:check()
    from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues
    units = store.units()
    if check is not None:check()
    ownership = ownership_issues(units)
    if ownership:
        raise ValueError(ownership[0].code + ': inspect project validation')
    from ModuleFolders.Service.Cache.CacheProject import CacheProject, CacheProjectStatistics
    from ModuleFolders.Service.Cache.CacheFile import CacheFile
    from ModuleFolders.Service.Cache.CacheItem import CacheItem
    meta=store.metadata()
    from .TranslationCommitter import TranslationCommitter
    policy=TranslationCommitter(store).policy
    project=CacheProject(project_id=meta['project_id'],project_type='RpgGame',
        project_name=meta.get('game_title','RPG'),input_path=str(store.root/'game-project.json'),
        stats_data=CacheProjectStatistics(),extra={'game_project_root':str(store.root),
            'game_dataset_revision':meta['dataset_revision']})
    analysis=store.analysis_record()
    project.set_extra('game_analysis_revision',analysis['revision'])
    project.set_extra('analysis_v1',analysis['data'] if analysis['dataset_revision']==meta['dataset_revision'] else {})
    for index,u in enumerate(units):
        if check is not None:check()
        rel=u.occurrences[0].relative_path if u.occurrences else 'unlocated'
        if rel not in project.files:project.add_file(CacheFile(storage_path=rel,file_project_type='RpgGame'))
        tr=store.translation(u.unit_id) or {}
        text,status,blocked_codes=_translation_state(u,tr,policy)
        item=CacheItem(text_index=index,source_text=u.source_text,
            translated_text=text,translation_status=status,
            extra={'game_project_root':str(store.root),'unit_id':u.unit_id,'source_hash':u.source_hash,
                'translation_revision':tr.get('revision',0),'dataset_revision':meta['dataset_revision'],
                'scene_id':u.scene_id,'game_context':u.context,'manual_locked':bool(tr.get('manual_locked')),
                'blocked_token_codes':blocked_codes})
        item.set_extra('game_storage_path',rel)
        project.files[rel].add_item(item)
    if check is not None:check()
    return project


def update_cached_item(item,store):
    from .TranslationCommitter import TranslationCommitter
    unit=store.unit(item.get_extra('unit_id'))
    if unit is None:
        raise ValueError('STALE_CACHE_PROJECTION: reload the project')
    tr=store.translation(unit.unit_id) or {}
    # Older source views can be cleared, but must never show a newly accepted
    # translation against their old source. Notification routing rejects this
    # mismatch before calling us; batch completion may still need this readback.
    if unit.source_hash!=item.get_extra('source_hash'):tr={**tr,'stale':True}
    text,status,blocked_codes=_translation_state(unit,tr,TranslationCommitter(store).policy)
    item.translated_text=text
    item.translation_status=status
    item.set_extra('translation_revision',tr.get('revision',0))
    item.set_extra('manual_locked',bool(tr.get('manual_locked')))
    item.set_extra('blocked_token_codes',blocked_codes)


def route_cache_reset(manager,task_mode):
    """Return None for ordinary documents; game resets commit to SQLite first."""
    project=manager.project
    if not is_game_projection(project):return None
    from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
    if type(task_mode) is not int or task_mode not in (TaskType.TRANSLATION,TaskType.POLISH):
        raise ValueError('RESET_MODE_INVALID')
    from .GameBatchPreparation import resolved_project_root_key
    from .ProjectLock import ProjectLock
    from .TranslationCommitter import TranslationCommitter
    from ModuleFolders.Service.Cache.CacheProject import CacheProjectStatistics
    root=game_project_root(project);root_key=resolved_project_root_key(root)
    with manager.file_lock:
        expected={};datasets=set();items=list(project.items_iter())
        for item in items:
            if resolved_project_root_key(item.get_extra('game_project_root'))!=root_key:
                raise ValueError('MIXED_GAME_PROJECT_BATCH')
            unit_id=item.get_extra('unit_id')
            if not isinstance(unit_id,str) or not unit_id or unit_id in expected:
                raise ValueError('RESET_PROJECTION_INVALID: duplicate or missing unit ID')
            revision=item.get_extra('translation_revision');dataset=item.get_extra('dataset_revision')
            if type(revision) is not int or revision<0 or type(dataset) is not int or dataset<0:
                raise ValueError('RESET_PROJECTION_INVALID: revision must be a nonnegative integer')
            expected[unit_id]={'source_hash':item.get_extra('source_hash'),'revision':revision}
            datasets.add(dataset)
        if len(datasets)>1:raise ValueError('DATASET_REVISION_CONFLICT')
        with ProjectLock(root),ProjectStore(root) as store:
            validate_game_project(project,store=store)
            dataset=next(iter(datasets)) if datasets else store.metadata()['dataset_revision']
            count=TranslationCommitter(store).reset_task_status(
                'translate' if task_mode==TaskType.TRANSLATION else 'polish',
                project_id=project.project_id,dataset_revision=dataset,expected_rows=expected)
            # SQLite has committed. Failures below cannot mean "reset rejected".
            try:
                # A status-only refresh would schedule source-blocked neighbors.
                fresh={item.get_extra('unit_id'):item for item in build_projection(store).items_iter()}
                if set(fresh)!=set(expected):raise ValueError('projection unit coverage changed')
                for item in items:
                    canonical=fresh[item.get_extra('unit_id')]
                    item.source_text=canonical.source_text
                    item.translated_text=canonical.translated_text
                    item.translation_status=canonical.translation_status
                    for key,value in canonical.extra.items():item.set_extra(key,value)
                if count:project.stats_data=CacheProjectStatistics()
            except Exception as error:
                project.set_extra('game_projection_refresh_required',True)
                raise ResetProjectionRefreshRequired(count) from error
    return count


def route_cache_edit(manager,storage_path,text_index,field_name,new_text,origin='manual'):
    project=manager.project
    item=_selected_item(project,storage_path,text_index)
    if not is_game_projection(project,items=(item,)):return False
    item=_require_selected_item(item,text_index)
    if field_name!='translated_text':raise ValueError('GAME_SOURCE_READ_ONLY: edit the profile or create a new source version')
    from .TranslationCommitter import TranslationCommitter
    from .ProjectLock import ProjectLock
    from ModuleFolders.Domain.GameProject.Models import TranslationProposal
    root=game_project_root(project,items=(item,))
    with ProjectLock(root),ProjectStore(root) as store:
        validate_game_project(project,items=(item,),store=store)
        result=TranslationCommitter(store).submit(TranslationProposal(item.get_extra('unit_id'),new_text,
            item.get_extra('source_hash'),expected_revision=item.get_extra('translation_revision',0),origin=origin))
        update_cached_item(item,store)
        if result.status not in {'accepted','duplicate'}:raise ValueError(f'GAME_TRANSLATION_{result.status.upper()}: review project issues')
    return True


def refresh_projection(project):
    if not is_game_projection(project):return project
    root=game_project_root(project,items=project.items_iter(),allow_refresh_required=True)
    with ProjectStore(root) as store:
        store._connection.execute('BEGIN')
        try:
            validate_game_project(project,store=store,allow_refresh_required=True)
            return build_projection(store)
        finally:store._connection.rollback()


def sync_generated_cache(manager,storage_path,text_index,text,*,expected_status=None):
    """UI notifications can reflect committed SQLite results, never create edits."""
    project=manager.project
    item=_require_selected_item(_selected_item(project,storage_path,text_index),text_index)
    root=game_project_root(project,items=(item,))
    with ProjectStore(root) as store:
        store._connection.execute('BEGIN')
        try:
            validate_game_project(project,items=(item,),store=store)
            unit=store.unit(item.get_extra('unit_id'))
            if unit is None or unit.source_hash!=item.get_extra('source_hash'):
                raise ValueError('STALE_CACHE_PROJECTION: reload the project')
            if manager.project is not project:return False
            update_cached_item(item,store)
            if expected_status is not None and (type(expected_status) is not int or expected_status!=item.translation_status):
                return False
            return item.translated_text==text
        finally:store._connection.rollback()


def apply_table_edit(page,table_item,storage_path,text_index,field_name,new_text):
    """Keep legacy Qt slots alive and restore their value after a rejected edit."""
    try:
        page.cache_manager.update_item_text(storage_path,text_index,field_name,new_text)
        return True
    except ValueError as exc:
        selected=_selected_item(page.cache_manager.project,storage_path,text_index)
        if not is_game_projection(page.cache_manager.project,items=(selected,)):raise
        current=page.cache_manager.project.get_file(storage_path).get_item(text_index)
        blocked=page.table.signalsBlocked();page.table.blockSignals(True)
        try:table_item.setText(getattr(current,field_name))
        finally:page.table.blockSignals(blocked)
        page.warning_toast('游戏工程校验',str(exc))
        return False
