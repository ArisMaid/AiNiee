"""Shared no-mutation preflight and no-overwrite JSON publication for games."""
from contextlib import ExitStack
import json,os,uuid
from pathlib import Path
from .PathGuard import safe_join,assert_disjoint,atomic_write
from .ProjectStore import ProjectStore
from .GameCacheIdentity import is_game_projection,game_project_root,validate_game_project

_MANAGED_EXPORT_ROOTS={'ainieeoutput','ainieepolishoutput','exports'}


def _output_directory(value):
    try:text=os.fspath(value)
    except TypeError as error:raise ValueError('GAME_OUTPUT_INVALID: choose an output directory') from error
    if not isinstance(text,str) or not text.strip():
        raise ValueError('GAME_OUTPUT_INVALID: choose a nonempty output directory')
    raw=Path(text)
    if '..' in raw.parts:raise ValueError('GAME_OUTPUT_INVALID: traversal is not allowed')
    output=Path(os.path.abspath(text))
    # Validate every lexical component before any resolution. This checks
    # junctions, ADS/reserved components, trailing dots/spaces and hard links.
    relative=output.relative_to(output.anchor)
    safe_join(output.anchor,relative.as_posix())
    existing=output
    while not existing.exists() and existing!=existing.parent:existing=existing.parent
    if not existing.is_dir():raise ValueError('GAME_OUTPUT_INVALID: a parent is not a directory')
    return output


def preflight_game_output(project,output_path,*,store=None):
    """Return a checked absolute directory, or None for an ordinary document.

    User exports may be independent directories, or live below three managed
    export roots inside a game project. Original game roots and all other
    project authority subtrees remain protected. No directory is created here.
    """
    if not is_game_projection(project):return None
    root=game_project_root(project,items=project.items_iter())
    output=_output_directory(output_path)
    with ExitStack() as resources:
        if store is None:store=resources.enter_context(ProjectStore(root))
        validate_game_project(project,store=store)
        metadata=store.metadata()
        assert_disjoint(metadata['source_root'],output)
        project_parts=tuple(part.casefold() for part in store.root.parts)
        output_parts=tuple(part.casefold() for part in output.parts)
        if output_parts[:len(project_parts)]==project_parts:
            relative_parts=output_parts[len(project_parts):]
            if not relative_parts or relative_parts[0] not in _MANAGED_EXPORT_ROOTS:
                raise ValueError('GAME_OUTPUT_PROTECTED_PROJECT: use AiNieeOutput, AiNieePolishOutput, exports, or an independent directory')
        else:assert_disjoint(store.root,output)
    return output


def write_game_json(project,output_path,kind,value,*,store=None,output_id=None):
    """Recheck the actual destination and publish one uniquely owned JSON file."""
    if kind not in ('game-translations','game-validation'):raise ValueError('GAME_OUTPUT_KIND_INVALID')
    output=preflight_game_output(project,output_path,store=store)
    if output is None:raise ValueError('GAME_OUTPUT_PROJECT_REQUIRED')
    identifier=uuid.uuid4().hex if output_id is None else output_id
    if not isinstance(identifier,str) or len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('GAME_OUTPUT_ID_INVALID')
    target=safe_join(output,f'{kind}-{identifier}.json')
    atomic_write(target,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'),overwrite=False)
    return target


def export_game_exchange(project,output_path):
    """Export one canonical as-of-revision exchange without invoking a game writer."""
    preflight_game_output(project,output_path)
    from .ProjectLock import ProjectLock
    from .GameProjectService import GameProjectService
    with ProjectLock(project.get_extra('game_project_root')),GameProjectService(project.get_extra('game_project_root')) as service:
        connection=service.store._connection
        connection.execute('BEGIN')
        try:
            rows=service.export_translations()
            return write_game_json(project,output_path,'game-translations',rows,store=service.store)
        finally:connection.rollback()
