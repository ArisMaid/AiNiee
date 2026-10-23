"""Ordered JSON/JS extraction checkpoints; publish the dataset in one transaction."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import uuid

from ModuleFolders.Domain.GameProject.AdapterProtocol import ExtractionResult
from ModuleFolders.Domain.GameProject.Models import Issue,TranslationUnit
from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy
from ModuleFolders.Infrastructure.GameAdapters.Registry import AdapterRegistry
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.ProfileLoader import load_profile,validate_profile
from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import extract_js_rules
from .BuildService import file_hash,write_json
from .JobControl import JobControl
from .JobController import begin_commit
from .OperationJournal import OperationJournal
from .PathGuard import safe_join,atomic_write
from .ProjectLock import JobLease

ALGORITHM='rpg-extraction-note-groups-v6'
_MAX_BLOB=128*1024*1024
_BASELINE=('project_id','source_root','engine','engine_version','game_id','source_manifest_hash',
    'dataset_revision','profile_hash','profile_id','token_policy_id','token_commands','token_literals',
    'font_aliases','profile_features','extraction_complete')


def _baseline(store):
    meta=store.metadata()
    return {key:meta.get(key) for key in _BASELINE}


def _preserve_note_permission_ids(previous,units):
    """Changing a note's write ownership must not discard an identical unit."""
    def key(unit):
        if len(unit.occurrences)!=1:return None
        occurrence=unit.occurrences[0];locator=occurrence.locator
        if not locator.get('note_tag'):return None
        return occurrence.relative_path,locator.get('pointer'),locator['note_tag'],occurrence.role
    old={key(u):u for u in previous if key(u) is not None}
    count=0
    for unit in units:
        prior=old.get(key(unit))
        if prior is None or not unit.occurrences[0].locator.get('note_group') or unit.unit_id==prior.unit_id:continue
        candidate=unit.to_dict();candidate['unit_id']=prior.unit_id
        candidate['occurrences'][0]['occurrence_id']=prior.occurrences[0].occurrence_id
        candidate['occurrences'][0]['locator'].pop('note_group')
        original=prior.to_dict();original['occurrences'][0]['locator'].pop('note_group',None)
        if candidate!=original:continue
        unit.unit_id=prior.unit_id;unit.occurrences[0].occurrence_id=prior.occurrences[0].occurrence_id;count+=1
    return count


def _profile(store,profile):
    if isinstance(profile,(str,Path)):profile=load_profile(profile)
    if profile is None:
        default=Path(__file__).resolve().parents[3]/'Resource/GameProfiles/selenoxia-test-0.141.yaml'
        if str(store.metadata().get('game_id'))=='33872391' and default.exists():profile=load_profile(default)
    if profile is not None:
        profile=validate_profile(profile)
        meta=store.metadata()
        if profile['engine']!=meta['engine']:raise ValueError('PROFILE_ENGINE_MISMATCH')
        wanted=profile.get('match',{}).get('game_id')
        if wanted is not None and str(wanted)!=str(meta.get('game_id')):raise ValueError('PROFILE_GAME_ID_MISMATCH')
    return profile or {}


def _plan(files,profile,data_dir):
    tracked={r['relative_path']:r for r in files if r.get('captured_path')}
    prefix=data_dir.rstrip('/')+'/'
    json_paths=sorted(path for path in tracked if path.startswith(prefix)
        and '/' not in path[len(prefix):] and path.lower().endswith('.json'))
    result=[dict(unit_id='json:'+path,kind='json',path=path,sha256=tracked[path]['sha256'],size=tracked[path]['size'])
        for path in json_paths]
    for index,rule in enumerate(profile.get('js_rules',[])):
        if rule.get('evidence_status')!='verified':continue
        path=rule['file'].replace('\\','/')
        if path not in tracked or not path.lower().endswith('.js'):
            raise ValueError('EXTRACTION_SOURCE_UNTRACKED: '+path)
        result.append(dict(unit_id='js:'+str(index),kind='js',path=path,
            sha256=tracked[path]['sha256'],size=tracked[path]['size']))
    return result


def _assert_current(store,inputs):
    if _baseline(store)!=inputs['baseline'] or store.files()!=inputs['files']:
        raise ValueError('EXTRACTION_RESUME_INPUT_CHANGED: start a new extraction for the current dataset')


def _verify_snapshots(store,inputs,control):
    for record in inputs['files']:
        if not record.get('captured_path'):continue
        control.check()
        if file_hash(safe_join(store.root,record['captured_path'],must_exist=True))!=record['sha256']:
            raise ValueError('SNAPSHOT_HASH_MISMATCH: '+record['relative_path'])
    for path,wanted in inputs['profile'].get('match',{}).get('fingerprints',{}).items():
        if file_hash(safe_join(store.root,'source/'+path,must_exist=True))!=wanted:
            raise ValueError('PROFILE_UNVERIFIED: fingerprint changed: '+path)


def _packed(result):
    return {'units':[u.to_dict() for u in result.units],'issues':[i.to_dict() for i in result.issues],
        'files':list(result.files),'stats':result.stats}


def _unpacked(value):
    if not isinstance(value,dict) or set(value)!={'units','issues','files','stats'}:
        raise ValueError('EXTRACTION_CHECKPOINT_INVALID')
    if (not isinstance(value['files'],list) or not all(isinstance(f,dict) for f in value['files'])
            or not isinstance(value['stats'],dict) or not isinstance(value['units'],list)
            or not isinstance(value['issues'],list)):
        raise ValueError('EXTRACTION_CHECKPOINT_INVALID')
    return ExtractionResult(tuple(TranslationUnit.from_dict(u) for u in value['units']),
        tuple(Issue.from_dict(i) for i in value['issues']),tuple(value['files']),value['stats'])


class _DocumentCache:
    def __init__(self,records,journal,plan,control,progress):
        self.records=records;self.journal=journal;self.plan=plan;self.control=control;self.progress=progress
        self.cached=journal.results();self.cursor=0;self.reused_json_files=0;self.reused_js_rules=0
        if len(self.cached)>len(plan) or any(row.get('unit_id')!=plan[i]['unit_id'] for i,row in enumerate(self.cached)):
            raise ValueError('EXTRACTION_CHECKPOINT_ORDER_CHANGED')

    @staticmethod
    def _check_result(result,spec):
        if not isinstance(result,ExtractionResult) or len(result.files)!=1:
            raise ValueError('EXTRACTION_CHECKPOINT_INVALID')
        record=result.files[0]
        if (not isinstance(record.get('relative_path'),str) or record['relative_path'].replace('\\','/')!=spec['path']
                or record.get('sha256')!=spec['sha256'] or record.get('size')!=spec['size']):
            raise ValueError('EXTRACTION_CHECKPOINT_SOURCE_CHANGED')

    def _consume(self,uid,kind,path,payload,compute):
        self.control.check(force=True)
        if self.cursor>=len(self.plan):raise ValueError('EXTRACTION_CHECKPOINT_ORDER_CHANGED')
        spec=self.plan[self.cursor]
        if (spec['unit_id']!=uid or spec['kind']!=kind or spec['path']!=path.replace('\\','/')
                or hashlib.sha256(payload).hexdigest()!=spec['sha256'] or len(payload)!=spec['size']):
            raise ValueError('EXTRACTION_CHECKPOINT_SOURCE_CHANGED')
        if self.cursor<len(self.cached):
            row=self.cached[self.cursor]
            relative=row.get('result_path')
            if (set(row)!={'unit_id','result_path','result_sha256'} or not isinstance(relative,str)
                    or not re.fullmatch(r'results/[a-f0-9]{32}\.json',relative)):
                raise ValueError('EXTRACTION_CHECKPOINT_INVALID')
            target=safe_join(self.records,relative,must_exist=True)
            if target.stat().st_size>_MAX_BLOB or file_hash(target)!=row.get('result_sha256'):
                raise ValueError('EXTRACTION_CHECKPOINT_CORRUPT')
            result=_unpacked(json.loads(target.read_text(encoding='utf-8')))
            if kind=='json':self.reused_json_files+=1
            else:self.reused_js_rules+=1
        else:
            result=compute();self._check_result(result,spec)
            data=json.dumps(_packed(result),sort_keys=True,ensure_ascii=False,allow_nan=False,
                separators=(',',':')).encode('utf-8')
            if len(data)>_MAX_BLOB:raise ValueError('EXTRACTION_CHECKPOINT_TOO_LARGE')
            relative='results/'+uuid.uuid4().hex+'.json'
            atomic_write(safe_join(self.records,relative),data)
            self.journal.append([{'unit_id':uid,'result_path':relative,'result_sha256':hashlib.sha256(data).hexdigest()}])
        self._check_result(result,spec)
        self.cursor+=1
        if self.progress:self.progress(self.cursor,len(self.plan),path)
        self.control.checkpoint('extracting',self.cursor)
        return result

    def document(self,path,payload,settings,compute):
        return self._consume('json:'+path,'json',path,payload,compute)

    def js_rule(self,index,rule,payload,compute):
        return self._consume('js:'+str(index),'js',rule['file'],payload,compute)

    def finish(self):
        if self.cursor!=len(self.plan) or self.journal.completed!=len(self.plan):
            raise ValueError('EXTRACTION_CHECKPOINT_INCOMPLETE')


def extract_project(store,profile=None,progress=None,on_job=None,resume_job_id=None):
    """Caller holds ProjectLock; manual translation edits after cancel remain valid."""
    if not store.metadata().get('scan_complete'):raise ValueError('SOURCE_SNAPSHOT_INCOMPLETE')
    with ExitStack() as resources:
        old=None
        if resume_job_id:
            old=next((j for j in store.jobs() if j['job_id']==resume_job_id),None)
            if not old or old['operation']!='EXTRACT':raise ValueError('EXTRACTION_JOB_NOT_FOUND')
            with JobLease(store.root,old['job_id']):pass
            if old['run_state'] in {'RUNNING','PAUSE_REQUESTED','PAUSED','CANCEL_REQUESTED','COMMITTING'}:
                old=store.update_job(old['job_id'],run_state='INTERRUPTED',error='PROCESS_INTERRUPTED')
            if old['run_state'] not in {'CANCELLED','FAILED','INTERRUPTED'}:raise ValueError('EXTRACTION_NOT_RESUMABLE')
            extraction_id=old.get('result',{}).get('extraction_id','')
            if not isinstance(extraction_id,str) or not re.fullmatch('[a-f0-9]{32}',extraction_id):
                raise ValueError('EXTRACTION_CHECKPOINT_MISSING')
            records=safe_join(store.root,'extractions/'+extraction_id,must_exist=True)
            target=safe_join(records,'inputs.json',must_exist=True)
            descriptor=old['result'].get('descriptor')
            if not isinstance(descriptor,dict) or file_hash(target)!=descriptor.get('input_digest'):
                raise ValueError('EXTRACTION_FROZEN_INPUT_CHANGED')
            inputs=json.loads(target.read_text(encoding='utf-8'))
            _assert_current(store,inputs)
            plan=_plan(inputs['files'],inputs['profile'],inputs['data_dir'])
            expected=dict(operation='extract',algorithm=ALGORITHM,input_digest=file_hash(target),item_count=len(plan))
            if descriptor!=expected:raise ValueError('EXTRACTION_CHECKPOINT_VERSION_CHANGED')
            journal=resources.enter_context(OperationJournal.open(safe_join(records,'resume.sqlite3',must_exist=True),expected))
        else:
            extraction_id=uuid.uuid4().hex;records=safe_join(store.root,'extractions/'+extraction_id)
        job=store.create_job('EXTRACT',{'extraction_id':extraction_id,'resume_from':resume_job_id or ''})
        store.update_job(job['job_id'],run_state='RUNNING',stage='freezing')
        resources.enter_context(JobLease(store.root,job['job_id']));control=JobControl(store,job['job_id'])
        from ModuleFolders.Infrastructure.Platform.OwnedProcess import worker_control
        resources.enter_context(worker_control(control.check_worker,job['job_id']))
        base={'extraction_id':extraction_id,'resume_from':resume_job_id or ''}
        store.update_job(job['job_id'],result=base)
        try:
            if not old:
                settings=_profile(store,profile)
                inputs={'profile':settings,'files':store.files(),'baseline':_baseline(store),
                    'data_dir':store.metadata().get('data_dir','data')}
                plan=_plan(inputs['files'],settings,inputs['data_dir'])
                records.mkdir(parents=True,exist_ok=False);write_json(records/'inputs.json',inputs)
                descriptor=dict(operation='extract',algorithm=ALGORITHM,
                    input_digest=file_hash(records/'inputs.json'),item_count=len(plan))
                journal=resources.enter_context(OperationJournal.create(records/'resume.sqlite3',descriptor))
            base.update(descriptor=descriptor,reused_json_files=0,reused_js_rules=0)
            store.update_job(job['job_id'],result=base)
            if on_job:on_job({'job_id':job['job_id'],'project_root':str(store.root)})
            control.checkpoint('verifying_inputs',0)
            if progress:progress(0,len(plan),'复核输入快照')
            _verify_snapshots(store,inputs,control)
            cache=_DocumentCache(records,journal,plan,control,progress)
            settings=inputs['profile'];snapshot=safe_join(store.root,'source',must_exist=True)
            adapter=AdapterRegistry().get(store.metadata().get('adapter_id','rpgmaker-native'))
            result=adapter.extract(snapshot,settings or None,progress=lambda *args:control.check(force=True),
                document_cache=cache.document)
            units=[u for u in result.units if not (any(o.relative_path.endswith('SH_NpcName.json')
                for o in u.occurrences) and re.fullmatch(r'actor\[\d+\]',u.source_text))]
            previous_units=store.units()
            units.extend(u for u in previous_units if u.kind=='image-text')
            issues=list(result.issues)
            if settings.get('js_rules'):
                extra,found,_=extract_js_rules(snapshot,settings['js_rules'],rule_cache=cache.js_rule)
                units.extend(extra);issues.extend(found)
            cache.finish()
            from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues
            ownership=ownership_issues(units)
            if ownership:
                store.put_issues(list(ownership),job_id=job['job_id'])
                raise ValueError('EXTRACTION_WRITE_CONFLICT: inspect project issues')
            if any(i.severity=='error' for i in issues):
                store.put_issues(issues,job_id=job['job_id'])
                raise ValueError('EXTRACTION_FAILED: inspect project issues')
            literals=settings.get('token_literals',[]);policy_id='rpgmaker-v3' if literals else 'rpgmaker-v2'
            policy=TokenPolicy(settings.get('token_commands',[]),policy_id,literal_tokens=literals);blocked=0
            for unit in units:unit.token_policy_id=policy_id
            note_ids_kept=_preserve_note_permission_ids(previous_units,units)
            for unit in units:
                control.check()
                _,found=policy.scan(unit.source_text,unit.unit_id)
                if found:blocked+=1;issues.extend(found)
            stats=dict(result.stats,unit_count=len(units),occurrence_count=sum(len(u.occurrences) for u in units),
                blocked_token_units=blocked,note_permission_ids_preserved=note_ids_kept)
            metadata={'extraction_complete':True,'extraction_stats':stats,'adapter_id':adapter.adapter_id,
                'adapter_version':adapter.version,'profile_id':settings.get('id',''),
                'profile_hash':hashlib.sha256(json.dumps(settings,sort_keys=True,allow_nan=False).encode()).hexdigest(),
                'profile_features':settings.get('required_features',[]),'token_policy_id':policy_id,
                'token_literals':list(literals),'font_aliases':settings.get('font_aliases',[]),
                'token_commands':settings.get('token_commands',[])}
            _assert_current(store,inputs)
            base.update(reused_json_files=cache.reused_json_files,reused_js_rules=cache.reused_js_rules)
            begin_commit(store,control)
            store.replace_units(units,extraction_metadata=metadata,extraction_issues=issues,
                extraction_completion={'job_id':job['job_id'],'result':base,'checkpoint':len(plan)})
            return base
        except Exception as exc:
            control.fail(exc)
            raise
