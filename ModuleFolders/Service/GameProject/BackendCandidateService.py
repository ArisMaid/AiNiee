"""Generate an isolated backend candidate and prove the approved JSON/JS plan."""
import hashlib
import json
from pathlib import Path
import uuid

from ModuleFolders.Domain.GameProject.Models import TranslationProposal,hash_text
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import patch_json,resolve_pointer,compile_json_changes
from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import rewrite_document,rewrite_js_document
from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import compile_js_changes,patch_js,audit_js_changes
from .PathGuard import safe_join,atomic_write
from .TranslationCommitter import TranslationCommitter


def generate_candidate(store,backend,backend_root,relative_path,*,on_job=None):
    """Only approved, accepted occurrences are passed to the selected writer.

    Results stay in the project work tree. Passing a semantic check does not
    replace native ownership or publish an independent game build.
    """
    from .ExternalTask import run_external_task
    baseline={}
    def compute(control):
        baseline.update({key:store.metadata()[key] for key in ('dataset_revision','content_revision')})
        from ModuleFolders.Infrastructure.GameAdapters.Capabilities import route_support
        support=route_support(backend,relative_path)
        if support['status']!='candidate_required':
            raise ValueError('BACKEND_FILE_UNSUPPORTED: '+support['reason'])
        from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues
        units = store.units()
        ownership = ownership_issues(units)
        if ownership:
            raise ValueError(ownership[0].code + ': inspect project validation')
        record=next((row for row in store.files() if row['relative_path']==relative_path),None)
        is_js=relative_path.casefold().endswith('.js')
        if not record or not record.get('captured_path') or not relative_path.casefold().endswith(('.json','.js')):
            raise ValueError('BACKEND_DOCUMENT_UNSUPPORTED')
        original=safe_join(store.root,record['captured_path'],must_exist=True).read_bytes()
        if hashlib.sha256(original).hexdigest()!=record['sha256']:raise ValueError('SNAPSHOT_HASH_MISMATCH')
        document=None if is_js else json.loads(original.decode('utf-8-sig'))
        replacements=[];changes=[]
        committer=TranslationCommitter(store)
        for unit in units:
            control.check()
            translation=store.translation(unit.unit_id) or {}
            if not translation.get('text') or translation.get('stale'):continue
            if translation.get('source_hash')!=unit.source_hash:raise ValueError('SOURCE_HASH_MISMATCH')
            proposal=TranslationProposal(unit.unit_id,translation['text'],unit.source_hash,
                translation['revision'],origin='validation')
            if any(i.severity=='error' for i in committer.validate_proposal(proposal)):
                raise ValueError('INVALID_ACCEPTED_TRANSLATION')
            for occurrence in unit.occurrences:
                if occurrence.relative_path!=relative_path:continue
                if occurrence.adapter_id!=('js-literal' if is_js else 'rpgmaker-native'):
                    raise ValueError('BACKEND_LOCATOR_UNSUPPORTED')
                if not is_js:
                    pointer=occurrence.locator['pointer'];old=resolve_pointer(document,pointer)
                    if not isinstance(old,str) or hash_text(old)!=occurrence.expected_value_hash:
                        raise ValueError('BACKEND_SOURCE_VALUE_CHANGED')
                replacements.append((occurrence,translation['text']))
        changes=(compile_js_changes if is_js else compile_json_changes)(original,replacements)
        expected=(patch_js if is_js else patch_json)(original,replacements)
        result=(rewrite_js_document if is_js else rewrite_document)(backend,relative_path,original,changes,
            safe_join(store.root,'work/backends'),Path(backend_root).absolute())
        actual=result.pop('output_bytes')
        canonical=lambda raw:json.dumps(json.loads(raw.decode('utf-8-sig')),sort_keys=True,
            ensure_ascii=False,separators=(',',':'),allow_nan=False)
        if is_js:audit_js_changes(original,actual,changes)
        elif canonical(actual)!=canonical(expected):raise ValueError('BACKEND_UNAPPROVED_DIFF')
        return actual,record,changes,result
    def publish(prepared):
        if any(store.metadata()[key]!=value for key,value in baseline.items()):
            raise ValueError('BACKEND_CANDIDATE_INPUT_CHANGED: generate a new candidate for current edits')
        actual,record,changes,result=prepared
        candidate=safe_join(store.root,f'work/candidates/{uuid.uuid4().hex}/{relative_path}')
        atomic_write(candidate,actual)
        return {'passed':True,'backend':backend,'relative_path':relative_path,
            'candidate':str(candidate),'source_sha256':record['sha256'],
            'output_sha256':hashlib.sha256(actual).hexdigest(),'sidecar_path':result['sidecar_path'],
            'changed_occurrences':len(changes),'capabilities':result['capabilities'],
            'content_revision':baseline['content_revision'],
            'published':False,'write_owner':'js-literal' if relative_path.casefold().endswith('.js') else 'rpgmaker-native'}
    return run_external_task(store,'BACKEND_CANDIDATE',{'backend':backend,'relative_path':relative_path},
        compute,publish,on_job)
