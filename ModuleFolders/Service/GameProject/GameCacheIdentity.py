"""Explicit game markers and canonical cache identity, without global state."""
from contextlib import ExitStack
import os
from pathlib import Path


def has_game_item_markers(item):
    extra=getattr(item,'extra',{}) if item is not None else {}
    return any(key in extra for key in ('game_project_root','game_storage_path','game_context'))


def is_game_projection(project,*,items=None):
    if project is None:return False
    if (getattr(project,'project_type',None)=='RpgGame'
            or 'game_project_root' in getattr(project,'extra',{})):return True
    return any(has_game_item_markers(item) for item in (project.items_iter() if items is None else items))


def game_root_key(value):
    try:
        text=os.fspath(value)
        if not isinstance(text,str) or not text.strip():raise ValueError('empty root')
        return os.path.normcase(os.path.abspath(text))
    except (TypeError,ValueError) as error:
        raise ValueError('GAME_PROJECT_IDENTITY_MISSING: reload the project') from error


def game_project_root(project,*,items=(),allow_refresh_required=False):
    if project is None:raise ValueError('GAME_PROJECT_IDENTITY_MISSING')
    if project.get_extra('game_projection_refresh_required') and not allow_refresh_required:
        raise ValueError('GAME_PROJECT_REFRESH_REQUIRED: 请重新加载游戏工程。')
    root=project.get_extra('game_project_root');key=game_root_key(root)
    for item in items:
        if item is None or game_root_key(item.get_extra('game_project_root'))!=key:
            raise ValueError('GAME_PROJECT_IDENTITY_CONFLICT: mixed item roots')
    return Path(os.path.abspath(os.fspath(root)))


def validate_game_project(project,*,items=(),store=None,allow_refresh_required=False):
    """Validate the selected projection scope against its canonical database."""
    from .ProjectStore import ProjectStore
    root=game_project_root(project,items=items,allow_refresh_required=allow_refresh_required)
    with ExitStack() as resources:
        if store is None:store=resources.enter_context(ProjectStore(root))
        if (game_root_key(store.root)!=game_root_key(root)
                or project.project_id!=store.metadata()['project_id']):
            raise ValueError('GAME_PROJECT_IDENTITY_CONFLICT: reload the project')
        return store.root
