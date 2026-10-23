"""Frozen-input offline validation with durable ordered checkpoints."""
from contextlib import ExitStack
import re
import uuid

from ModuleFolders.Domain.GameProject.Models import Issue,TranslationProposal
from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues
from .BackendRoutes import route_issues
from .BuildService import file_hash,write_json
from .JobControl import JobControl
from .JobController import begin_commit
from .PathGuard import safe_join
from .ProjectLock import JobLease
from .ProjectStore import ProjectStore
from .TranslationCommitter import TranslationCommitter

ALGORITHM='rpg-validation-ownership-v1'
_BATCH_SIZE=64


def _global_issues(store,units):
    return list(ownership_issues(units))+list(route_issues(
        store.metadata().get('backend_routes',{}),(r['relative_path'] for r in store.files())))


def _unit_issues(committer,unit,translation):
    _,issues=committer.policy.scan(unit.source_text,unit.unit_id)
    issues=list(issues)
    if translation and translation.get('text'):
        issues.extend(committer.validate_proposal(TranslationProposal(unit.unit_id,translation['text'],
            translation['source_hash'],expected_revision=translation['revision'],origin='validation')))
    return issues


def _report(store,units,translations,issues):
    translated=sum(bool((tr:=translations[u.unit_id]) and tr.get('text') and not tr.get('stale')
        and tr.get('source_hash')==u.source_hash) for u in units)
    return {'passed':not any(i.severity=='error' for i in issues),'issues':[i.to_dict() for i in issues],
        'runtime_validation':'not_run','untranslated':len(units)-translated,
        'input_revision':store.metadata()['content_revision']}


def inspect_project(store):
    """No writes or lock files: useful for immutable package/read-only audits."""
    units=store.units();translations={u.unit_id:store.translation(u.unit_id) for u in units}
    committer=TranslationCommitter(store);issues=_global_issues(store,units)
    for unit in units:issues.extend(_unit_issues(committer,unit,translations[unit.unit_id]))
    return _report(store,units,translations,issues)


def _assert_current(live,frozen):
    left=live.metadata();right=frozen.metadata()
    if any(left.get(key)!=right.get(key) for key in ('project_id','dataset_revision','content_revision')):
        raise ValueError('VALIDATION_RESUME_INPUT_CHANGED: run a new validation for current edits')


def validate_project(store,progress=None,on_job=None,resume_job_id=None):
    """Caller holds ProjectLock. A failed attempt never publishes a valid report."""
    from .OperationJournal import OperationJournal
    with ExitStack() as resources:
        old=None;descriptor=None
        if resume_job_id:
            old=next((j for j in store.jobs() if j['job_id']==resume_job_id),None)
            if not old or old['operation']!='VALIDATE':raise ValueError('VALIDATION_JOB_NOT_FOUND')
            with JobLease(store.root,old['job_id']):pass
            if old['run_state'] in {'RUNNING','PAUSED','PAUSE_REQUESTED','CANCEL_REQUESTED','COMMITTING'}:
                old=store.update_job(old['job_id'],run_state='INTERRUPTED',error='PROCESS_INTERRUPTED')
            if old['run_state'] not in {'INTERRUPTED','FAILED','CANCELLED'}:
                raise ValueError('VALIDATION_NOT_RESUMABLE')
            validation_id=old.get('result',{}).get('validation_id','')
            descriptor=old.get('result',{}).get('descriptor')
            if not isinstance(validation_id,str) or not re.fullmatch('[a-f0-9]{32}',validation_id):
                raise ValueError('VALIDATION_CHECKPOINT_MISSING')
            records=safe_join(store.root,'validations/'+validation_id,must_exist=True)
            snapshot=safe_join(records,'project.sqlite3',must_exist=True)
            if not isinstance(descriptor,dict) or file_hash(snapshot)!=descriptor.get('input_digest'):
                raise ValueError('VALIDATION_FROZEN_INPUT_CHANGED')
            frozen=resources.enter_context(ProjectStore(records,readonly=True))
            _assert_current(store,frozen)
            units=frozen.units()
            expected=dict(operation='validate',algorithm=ALGORITHM,input_digest=file_hash(snapshot),item_count=len(units))
            if descriptor!=expected:raise ValueError('VALIDATION_CHECKPOINT_VERSION_CHANGED')
            journal=resources.enter_context(OperationJournal.open(safe_join(records,'resume.sqlite3',must_exist=True),expected))
        else:
            validation_id=uuid.uuid4().hex
            records=safe_join(store.root,'validations/'+validation_id)
        job=store.create_job('VALIDATE',{'validation_id':validation_id,'resume_from':resume_job_id or ''})
        store.update_job(job['job_id'],run_state='RUNNING',stage='freezing')
        resources.enter_context(JobLease(store.root,job['job_id']))
        control=JobControl(store,job['job_id'])
        from ModuleFolders.Infrastructure.Platform.OwnedProcess import worker_control
        resources.enter_context(worker_control(control.check_worker,job['job_id']))
        base_result={'validation_id':validation_id,'resume_from':resume_job_id or ''}
        store.update_job(job['job_id'],result=base_result)
        try:
            if not old:
                records.mkdir(parents=True,exist_ok=False)
                store.snapshot(records/'project.sqlite3')
                frozen=resources.enter_context(ProjectStore(records,readonly=True))
                units=frozen.units()
                descriptor=dict(operation='validate',algorithm=ALGORITHM,
                    input_digest=file_hash(records/'project.sqlite3'),item_count=len(units))
                journal=resources.enter_context(OperationJournal.create(records/'resume.sqlite3',descriptor))
            base_result.update(descriptor=descriptor,reused_units=journal.completed)
            store.update_job(job['job_id'],result=base_result)
            if on_job:on_job({'job_id':job['job_id'],'project_root':str(store.root)})
            control.checkpoint('validating',journal.completed)
            translations={u.unit_id:frozen.translation(u.unit_id) for u in units}
            committer=TranslationCommitter(frozen);issues=_global_issues(frozen,units)
            cached=journal.results()
            for index,row in enumerate(cached):
                if (set(row)!={'unit_id','issues'} or row['unit_id']!=units[index].unit_id
                        or not isinstance(row['issues'],list)):
                    raise ValueError('VALIDATION_CHECKPOINT_INVALID')
                issues.extend(Issue.from_dict(issue) for issue in row['issues'])
            if progress:progress(journal.completed,len(units),'已复核校验检查点')
            pending=[]
            for unit in units[journal.completed:]:
                control.check()
                found=_unit_issues(committer,unit,translations[unit.unit_id])
                pending.append({'unit_id':unit.unit_id,'issues':[i.to_dict() for i in found]})
                issues.extend(found)
                if len(pending)==_BATCH_SIZE:
                    journal.append(pending);pending=[]
                    if progress:progress(journal.completed,len(units),'校验文本')
                    control.checkpoint('validating',journal.completed)
            if pending:
                journal.append(pending)
                if progress:progress(journal.completed,len(units),'校验文本')
                control.checkpoint('validating',journal.completed)
            _assert_current(store,frozen)
            report=_report(frozen,units,translations,issues)
            report.update(validation_id=validation_id,job_id=job['job_id'],reused_units=base_result['reused_units'])
            begin_commit(store,control)
            report_path=safe_join(records,'report-'+job['job_id']+'.json')
            write_json(report_path,report)
            store.update_job(job['job_id'],run_state='COMPLETED',stage='complete',checkpoint=journal.completed,
                result=dict(base_result,report_path=str(report_path),report_sha256=file_hash(report_path),
                    passed=report['passed'],issue_count=len(issues)))
            return report
        except Exception as exc:
            control.fail(exc)
            raise
