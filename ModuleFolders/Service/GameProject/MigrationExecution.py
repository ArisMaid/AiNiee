"""Resume a reviewed migration from atomic accepted proposal receipts."""
from contextlib import ExitStack
import json
import re
import uuid

from .BuildService import file_hash,write_json
from .JobControl import JobControl
from .JobController import begin_commit
from .MigrationLedger import reconstruct_receipts
from .MigrationService import apply_migration
from .PathGuard import safe_join
from .ProjectLock import ProjectLock,JobLease
from .ProjectStore import ProjectStore

ALGORITHM='migration-accepted-receipts-v1'
_BASELINE=('project_id','source_root','source_manifest_hash','engine','engine_version','game_id',
    'dataset_revision','profile_id','profile_hash','token_policy_id','token_commands','token_literals',
    'font_aliases','profile_features','target_language','migration_lineage','font_settings',
    'layout_settings','backend_routes','image_settings','scan_complete','extraction_complete')
_ACTIVE={'RUNNING','PAUSE_REQUESTED','PAUSED','CANCEL_REQUESTED','COMMITTING'}


def _baseline(store,source=False):
    meta=store.metadata()
    return {key:meta.get(key) for key in (*_BASELINE,*(('content_revision',) if source else ()))}


def _read(path,digest,limit=128*1024*1024):
    if path.stat().st_size>limit or file_hash(path)!=digest:raise ValueError('MIGRATION_FROZEN_INPUT_CHANGED')
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):raise ValueError('MIGRATION_FROZEN_INPUT_INVALID')
    return value


def _probe(new_project,plan_id,resume_job_id):
    from .MigrationWorkflow import _root,_registry
    new_root=_root(new_project)
    with ProjectLock(new_root),ProjectStore(new_root) as store:
        prior=None
        if resume_job_id:
            prior=next((j for j in store.jobs() if j['job_id']==resume_job_id),None)
            if not prior or prior['operation']!='MIGRATE':raise ValueError('MIGRATION_JOB_NOT_FOUND')
            payload=prior['payload']
            if payload.get('algorithm')!=ALGORITHM:raise ValueError('MIGRATION_CHECKPOINT_MISSING')
            plan_id=payload.get('plan_id')
        if not isinstance(plan_id,str) or not re.fullmatch('[a-f0-9]{32}',plan_id):
            raise ValueError('MIGRATION_REVIEW_NOT_FOUND')
        registered=_registry(store).get(plan_id)
        if not isinstance(registered,dict):raise ValueError('MIGRATION_REVIEW_NOT_FOUND')
        return new_root,plan_id,dict(registered),prior


def run_review(new_project,plan_id=None,*,resume_job_id=None,progress=None,on_job=None):
    from .MigrationWorkflow import _stores,_registry,_binding,_ALGORITHM
    new_root,plan_id,expected,prior=_probe(new_project,plan_id,resume_job_id)
    with _stores(expected['old_root'],new_root) as (old,new,old_root,new_root),ExitStack() as resources:
        current=_registry(new).get(plan_id)
        if current!=expected:raise ValueError('MIGRATION_REVIEW_CHANGED')
        if current.get('state')!='planned':raise ValueError('MIGRATION_REVIEW_ALREADY_APPLIED')
        relative='work/migration-review/'+plan_id+'/plan.json'
        if current.get('path')!=relative:raise ValueError('MIGRATION_REVIEW_INVALID')
        target=safe_join(new.root,relative,must_exist=True)
        try:envelope=_read(target,current.get('sha256'))
        except ValueError as error:raise ValueError('MIGRATION_REVIEW_TAMPERED') from error
        if (type(envelope.get('schema_version')) is not int or envelope['schema_version']!=1
                or envelope.get('algorithm')!=_ALGORITHM or envelope.get('plan_id')!=plan_id):
            raise ValueError('MIGRATION_REVIEW_INVALID')
        if envelope.get('plan',{}).get('identity',{}).get('verified') is not True:
            raise ValueError('MIGRATION_IDENTITY_UNVERIFIED')
        if prior:
            resources.enter_context(JobLease(new.root,prior['job_id']))
            prior=next(j for j in new.jobs() if j['job_id']==prior['job_id'])
            if prior['run_state']=='QUEUED':
                prior=new.update_job(prior['job_id'],run_state='FAILED',error='PROCESS_INTERRUPTED_BEFORE_RUN')
            elif prior['run_state'] in _ACTIVE:
                prior=new.update_job(prior['job_id'],run_state='INTERRUPTED',error='PROCESS_INTERRUPTED')
            if prior['run_state'] not in {'CANCELLED','FAILED','INTERRUPTED'}:
                raise ValueError('MIGRATION_NOT_RESUMABLE')
            payload=dict(prior['payload'])
            inputs_path=payload.get('inputs_path','')
            if not isinstance(inputs_path,str) or not re.fullmatch(
                    'work/migration-review/'+plan_id+r'/attempt-inputs/[a-f0-9]{32}\.json',inputs_path):
                raise ValueError('MIGRATION_CHECKPOINT_MISSING')
            inputs=_read(safe_join(new.root,inputs_path,must_exist=True),payload.get('inputs_sha256'),1024*1024)
            binding=_binding(old,new,old_root,new_root);frozen_binding=dict(envelope.get('binding',{}))
            binding.pop('new_content_revision',None);frozen_binding.pop('new_content_revision',None)
            if (type(inputs.get('schema_version')) is not int or inputs['schema_version']!=1
                    or inputs.get('algorithm')!=ALGORITHM or inputs.get('plan_id')!=plan_id
                    or inputs.get('plan_sha256')!=current['sha256']
                    or binding!=frozen_binding or inputs.get('old')!=_baseline(old,source=True)
                    or inputs.get('new')!=_baseline(new)):
                raise ValueError('MIGRATION_RESUME_INPUT_CHANGED: generate a new review')
        else:
            if envelope.get('binding')!=_binding(old,new,old_root,new_root):
                raise ValueError('MIGRATION_REVIEW_STALE: prepare a new review after edits')
            inputs={'schema_version':1,'algorithm':ALGORITHM,'plan_id':plan_id,'plan_sha256':current['sha256'],
                'old':_baseline(old,source=True),'new':_baseline(new)}
            inputs_path='work/migration-review/'+plan_id+'/attempt-inputs/'+uuid.uuid4().hex+'.json'
            target=safe_join(new.root,inputs_path);write_json(target,inputs)
            payload={'algorithm':ALGORITHM,'plan_id':plan_id,'inputs_path':inputs_path,'inputs_sha256':file_hash(target)}
        payload['resumed_from']=prior['job_id'] if prior else ''
        job=new.create_job('MIGRATE',payload)
        resources.enter_context(JobLease(new.root,job['job_id']))
        new.update_job(job['job_id'],run_state='RUNNING',stage='verifying')
        control=JobControl(new,job['job_id'])
        try:
            if on_job:on_job(job['job_id'])
            control.check(force=True)
            matches=envelope['plan']['matches'];delivery_id='migration-review:'+plan_id
            receipts=reconstruct_receipts(matches,new.proposals(),delivery_job_id=delivery_id,
                old_project_id=inputs['old']['project_id'])
            results=receipts['results'];reused=receipts['completed']
            control.checkpoint('verifying',reused)
            if progress:progress(reused,len(matches),'已提交记录已核对')
            def after_commit(match,result):
                if result.status!='accepted':raise ValueError('MIGRATION_SUBMISSION_REJECTED: '+result.status)
                results.append(result.to_dict())
                if progress:progress(len(results),len(matches),match['new_unit_id'])
                control.checkpoint('migrating',len(results))
            apply_migration(old,new,{'matches':receipts['pending_matches']},job_id=delivery_id,
                check=control.check,on_result=after_commit)
            # An accepted receipt is the durable checkpoint, even if cancellation
            # or process death prevented the subsequent progress write.
            control.check(force=True);begin_commit(new,control)
            report={'plan_id':plan_id,'job_id':job['job_id'],'algorithm':ALGORITHM,'resumed_from':payload['resumed_from'],
                'results':results,'accepted':len(results),'rejected':0,'passed':True,'reused_units':reused,
                'new_units':len(results)-reused,'historical_accepted_receipts':True}
            report_path=safe_join(new.root,'work/migration-review/'+plan_id+'/reports/'+uuid.uuid4().hex+'.json')
            write_json(report_path,report)
            applied=dict(current,state='applied',result_path=str(report_path),result_sha256=file_hash(report_path),
                target_content_revision=new.metadata()['content_revision'])
            new.complete_migration_review(job['job_id'],plan_id,current,applied,report)
            return report
        except BaseException as error:
            control.fail(error)
            raise
