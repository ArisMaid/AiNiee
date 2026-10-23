"""Persist a reviewable migration plan and apply only the registered current plan."""
from contextlib import contextmanager,ExitStack,closing
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .BuildService import file_hash,write_json
from .Lineage import build_confirmation
from .MigrationService import plan_migration,_REASON_DETAIL
from .PathGuard import safe_join,assert_disjoint
from .ProjectLock import ProjectLock
from .ProjectStore import ProjectStore

_ALGORITHM='migration-review-note-tags-v2'
_MAX_PLAN=128*1024*1024
_REASONS={'exact_location':'原文、位置及语境一致','unique_scene_anchor':'双向唯一的场景锚点',
    'NEW':'目标工程新增单元','ORPHANED':'旧工程中未找到可靠对应的单元'}


def _root(path):
    target=Path(path).absolute()
    if target.is_file():target=target.parent
    safe_join(target,'project.sqlite3',must_exist=True)
    return target.resolve()


@contextmanager
def _stores(old_root,new_root):
    old_root=_root(old_root);new_root=_root(new_root)
    if old_root==new_root:raise ValueError('MIGRATION_SAME_PROJECT')
    assert_disjoint(old_root,new_root)
    with ExitStack() as resources:
        for root in sorted((old_root,new_root),key=lambda p:str(p).casefold()):resources.enter_context(ProjectLock(root))
        new=resources.enter_context(ProjectStore(new_root))
        snapshot=safe_join(new.root,'work/migration-read/'+uuid.uuid4().hex)
        snapshot.mkdir(parents=True,exist_ok=False)
        target=snapshot/'project.sqlite3'
        # A read-only SQLite backup includes a live source WAL. No immutable
        # reader is opened against a potentially incomplete source main file.
        with target.open('xb'):pass
        with closing(sqlite3.connect(safe_join(old_root,'project.sqlite3',must_exist=True).as_uri()+'?mode=ro',uri=True)) as source:
            with closing(sqlite3.connect(target)) as copied:
                deadline=time.monotonic()+30
                def checkpoint(status,remaining,total):
                    if time.monotonic()>deadline:raise ValueError('MIGRATION_SNAPSHOT_TIMEOUT')
                source.backup(copied,pages=512,progress=checkpoint,sleep=.05)
        old=resources.enter_context(ProjectStore(snapshot,readonly=True))
        yield old,new,old_root,new_root


def _binding(old,new,old_root,new_root):
    before=old.metadata();after=new.metadata()
    return dict(old_root=str(old_root),new_root=str(new_root),**{
        side+'_'+key:meta.get(key) for side,meta in (('old',before),('new',after))
        for key in ('project_id','source_manifest_hash','dataset_revision','content_revision')})


def _registry(store):
    value=store.metadata().get('migration_reviews',{})
    if not isinstance(value,dict):raise ValueError('MIGRATION_REVIEW_REGISTRY_INVALID')
    return value


def _details(store):
    result={}
    for unit in store.units():
        tr=store.translation(unit.unit_id) or {}
        result[unit.unit_id]={'source':unit.source_text,'translation':tr.get('text',''),
            'scene':unit.scene_id,'kind':unit.kind,'manual_locked':bool(tr.get('manual_locked')),
            'locations':[{'file':o.relative_path,'locator':{k:v for k,v in o.locator.items()
                if k in {'pointer','start','end','object_path','scope_function','property_path','region_id','box'}}} for o in unit.occurrences]}
    return result


def prepare_review(old_project,new_project,confirm_lineage=False):
    with _stores(old_project,new_project) as (old,new,old_root,new_root):
        if confirm_lineage:
            record=build_confirmation(old.metadata(),new.metadata(),confirmed=confirm_lineage)
            new.update_metadata({'migration_lineage':record})
        plan=plan_migration(old,new);identifier=uuid.uuid4().hex
        envelope={'schema_version':1,'algorithm':_ALGORITHM,'plan_id':identifier,
            'binding':_binding(old,new,old_root,new_root),'plan':plan,
            'details':{'old':_details(old),'new':_details(new)}}
        relative='work/migration-review/'+identifier+'/plan.json'
        target=safe_join(new.root,relative);write_json(target,envelope)
        registry=_registry(new)
        registry[identifier]={'path':relative,'sha256':file_hash(target),'old_root':str(old_root),'state':'planned'}
        new.update_metadata({'migration_reviews':registry})
        return dict(envelope,plan_path=str(target))


def apply_review(new_project,plan_id,*,progress=None,on_job=None):
    from .MigrationExecution import run_review
    return run_review(new_project,plan_id,progress=progress,on_job=on_job)


def resume_review(new_project,job_id,*,progress=None,on_job=None):
    from .MigrationExecution import run_review
    return run_review(new_project,resume_job_id=job_id,progress=progress,on_job=on_job)


def load_review(new_project,plan_id):
    """Load a registered historical review for display; application rechecks it."""
    if not isinstance(plan_id,str) or not re.fullmatch('[a-f0-9]{32}',plan_id):raise ValueError('MIGRATION_REVIEW_NOT_FOUND')
    with ProjectLock(_root(new_project)),ProjectStore(_root(new_project)) as store:
        record=_registry(store).get(plan_id)
        relative='work/migration-review/'+plan_id+'/plan.json'
        if not isinstance(record,dict) or record.get('path')!=relative:raise ValueError('MIGRATION_REVIEW_NOT_FOUND')
        target=safe_join(store.root,relative,must_exist=True)
        if target.stat().st_size>_MAX_PLAN or file_hash(target)!=record.get('sha256'):
            raise ValueError('MIGRATION_REVIEW_TAMPERED')
        envelope=json.loads(target.read_text(encoding='utf-8'))
        if envelope.get('plan_id')!=plan_id:raise ValueError('MIGRATION_REVIEW_INVALID')
        return dict(envelope,plan_path=str(target))


def reconciliation_rows(envelope,category='all'):
    rows=[]
    for kind,entries in envelope['plan']['reconciliation'].items():
        if category!='all' and kind!=category:continue
        for entry in entries:
            reason=entry.get('reason','')
            rows.append(dict(entry,category=kind,explanation=_REASONS.get(reason,_REASON_DETAIL.get(reason,reason))))
    return rows
