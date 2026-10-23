"""Build immutable-input, independently auditable game copies. Never delete files."""
from __future__ import annotations
from collections import defaultdict
import hashlib
import json
import os
import shutil
from pathlib import Path
import uuid

from .PathGuard import safe_join, assert_disjoint, atomic_write
from .ProjectStore import ProjectStore
from .TranslationCommitter import TranslationCommitter
from ModuleFolders.Domain.GameProject.Models import TranslationProposal


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_file_set(root):
    """Return protected input files, excluding only runtime saves and logs."""
    root=Path(root)
    result=set()
    for folder,directories,names in os.walk(root,followlinks=False):
        for name in directories:
            safe_join(root,(Path(folder)/name).relative_to(root).as_posix(),must_exist=True)
        for name in names:
            rel=(Path(folder)/name).relative_to(root).as_posix()
            safe_join(root,rel,must_exist=True)
            if rel.casefold().startswith('save/') or rel.casefold() in {'debug.log','error.log'}:continue
            result.add(rel)
    return result


def write_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def _strict_json(data):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('DUPLICATE_JSON_KEY')
            result[key]=value
        return result
    def constant(value):raise ValueError('INVALID_JSON_CONSTANT')
    return json.loads(data.decode('utf-8-sig'),object_pairs_hook=pairs,parse_constant=constant)


def _json_canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def _frozen_hash(records_root):
    for suffix in ('-wal','-journal'):
        path=safe_join(records_root,'project.sqlite3'+suffix)
        if path.exists() and path.stat().st_size:raise ValueError('BUILD_FROZEN_SNAPSHOT_DIRTY')
    return file_hash(safe_join(records_root,'project.sqlite3',must_exist=True))


def _checkpoint_matches(record,relative_path,replacements,original,target,routes,meta):
    """A journal hash proves file identity; the frozen write plan proves meaning."""
    if not replacements:return record['output_sha256']==record['original_sha256'] and record['writer'].get('id')=='copy'
    kinds={o.adapter_id for o,_ in replacements}
    if kinds=={'rpgmaker-native'}:
        from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import patch_json
        route=routes.get(relative_path)
        expected_writer=route['backend'] if route else 'rpgmaker-native'
        if record['writer'].get('id')!=expected_writer:return False
        if route and record['writer'].get('upstream_fingerprint')!=route['fingerprint']['digest']:return False
        try:return _json_canonical(_strict_json(target.read_bytes()))==_json_canonical(_strict_json(patch_json(original,replacements)))
        except (ValueError,UnicodeError):return False
    if kinds=={'js-literal'}:
        from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import patch_js,compile_js_changes,audit_js_changes
        route=routes.get(relative_path)
        if record['writer'].get('id')!=(route['backend'] if route else 'js-literal'):return False
        if route and record['writer'].get('upstream_fingerprint')!=route['fingerprint']['digest']:return False
        if not route:return target.read_bytes()==patch_js(original,replacements)
        try:audit_js_changes(original,target.read_bytes(),compile_js_changes(original,replacements))
        except (ValueError,UnicodeError):return False
        return True
    if kinds=={'image-region'}:
        expected=meta.get('image_settings',{}).get(relative_path,{}).get('approved',{}).get('sha256')
        return record['writer'].get('id')=='image-region' and record['output_sha256']==expected
    return False


class BuildService:
    def __init__(self, store):
        self.store = store

    def build(self, output_root=None, *, test=False, progress=None, runtime_capture=False, on_job=None, resume_build_id=None):
        from .JobControl import JobControl
        job=self.store.create_job('BUILD_RESUME' if resume_build_id else 'BUILD',{
            'output_root':str(Path(output_root).absolute()) if output_root is not None else '',
            'test':bool(test),'runtime_capture':bool(runtime_capture),'resume_build_id':resume_build_id or ''})
        self.store.update_job(job['job_id'],run_state='RUNNING',stage='preflight')
        control=JobControl(self.store,job['job_id'])
        from .ProjectLock import JobLease
        lease=JobLease(self.store.root,job['job_id']);lease.__enter__()
        try:
            if on_job:on_job({'job_id':job['job_id'],'project_root':str(self.store.root)})
            result=self._build(output_root,test=test,progress=progress,
                runtime_capture=runtime_capture,control=control,resume_build_id=resume_build_id)
            self.store.update_job(job['job_id'],run_state='COMPLETED',stage='complete',
                result={'build_id':result['build_id'],'output_path':result['output_path']})
            return result
        except Exception as exc:
            control.fail(exc)
            raise
        finally:lease.__exit__(None,None,None)

    def _build(self, output_root, *, test=False, progress=None, runtime_capture=False, control, resume_build_id=None):
        from contextlib import ExitStack
        with ExitStack() as resources:
            from ModuleFolders.Infrastructure.Platform.OwnedProcess import worker_control
            resources.enter_context(worker_control(control.check_worker,control.job_id))
            return self._build_attempt(output_root,test=test,progress=progress,runtime_capture=runtime_capture,
                control=control,resume_build_id=resume_build_id,resources=resources)

    def _build_attempt(self, output_root, *, test, progress, runtime_capture, control, resume_build_id, resources):
        from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import patch_json
        from .JobController import begin_commit
        from .BuildJournal import BuildJournal
        control.check(force=True)
        meta = self.store.metadata()
        project_root = Path(self.store.root).resolve()
        source = Path(meta['source_root']).resolve()
        journal=None;attempt_id=None;resumed_files=0;retained_files=[]
        if resume_build_id:
            journal=resources.enter_context(BuildJournal.open(project_root,resume_build_id))
            descriptor=journal.descriptor
            if descriptor['project_id']!=meta['project_id'] or Path(descriptor['source_root']).resolve()!=source:
                raise ValueError('BUILD_RESUME_PROJECT_MISMATCH')
            output_root=Path(descriptor['output_root']);test=descriptor['test'];runtime_capture=descriptor['runtime_capture']
            build_id=resume_build_id
        else:
            if output_root is None:raise ValueError('OUTPUT_ROOT_REQUIRED')
            output_root = Path(output_root).absolute()
            build_id = uuid.uuid4().hex
        if runtime_capture and not test:
            raise ValueError('RUNTIME_CAPTURE_REQUIRES_TEST_BUILD')
        safe_join(output_root,'.boundary-check')
        assert_disjoint(source, project_root, output_root)
        records_root = safe_join(project_root, f'builds/{build_id}')
        if not resume_build_id:
            records_root.mkdir(parents=True, exist_ok=False)
            self.store.snapshot(records_root / 'project.sqlite3')
        elif _frozen_hash(records_root)!=descriptor['frozen_sha256']:
            raise ValueError('BUILD_FROZEN_SNAPSHOT_CHANGED')
        frozen = resources.enter_context(ProjectStore(records_root,readonly=True))
        meta = frozen.metadata()
        staging = safe_join(output_root, f'.staging-{build_id}')
        final = safe_join(output_root, f'game-zh-CN-{build_id}')
        published=final.exists()
        if published and not resume_build_id:
            raise ValueError('BUILD_ALREADY_PUBLISHED: verify the existing output; it will not be overwritten')
        output_root.mkdir(parents=True, exist_ok=True)
        required = (0 if resume_build_id else sum(r['size'] for r in frozen.files())) + 64*1024*1024
        if shutil.disk_usage(output_root).free < required:
            raise ValueError(f'INSUFFICIENT_DISK_SPACE: need at least {required} bytes')
        if resume_build_id and not published:
            safe_join(output_root,staging.name,must_exist=True)
            if not staging.is_dir():raise ValueError('BUILD_STAGING_MISSING')
        elif not resume_build_id:staging.mkdir(exist_ok=False)
        self.store.update_job(control.job_id,result={'build_id':build_id,'staging':str(staging),
            'resumed':bool(resume_build_id)})
        try:
            changes = defaultdict(list)
            approved_units = defaultdict(set)
            missing = []
            validator = TranslationCommitter(frozen)
            units = frozen.units()
            from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues
            ownership = ownership_issues(units)
            if ownership:
                raise ValueError(ownership[0].code + ': inspect project validation')
            translations_digest = []
            for unit in units:
                control.check()
                tr = frozen.translation(unit.unit_id)
                if not tr or not tr.get('text') or tr.get('stale') or tr.get('status') == 'stale':
                    missing.append(unit.unit_id)
                    continue
                proposal = TranslationProposal(unit.unit_id, tr['text'], tr['source_hash'],
                    expected_revision=tr['revision'], origin='build-validation')
                issues = validator.validate_proposal(proposal)
                if tr['source_hash'] != unit.source_hash or any(i.severity == 'error' for i in issues):
                    raise ValueError(f'TRANSLATION_INVALID: {unit.unit_id}')
                translations_digest.append((unit.unit_id, tr['revision'], tr['text']))
                for occurrence in unit.occurrences:
                    changes[occurrence.relative_path].append((occurrence, tr['text']))
                    approved_units[occurrence.relative_path].add(unit.unit_id)
            if missing and not test:
                raise ValueError(f'UNTRANSLATED_UNITS: {len(missing)}; use explicit test mode for partial copies')
            files = frozen.files()
            expected_source={r['relative_path'] for r in files if not (
                r['relative_path'].casefold().startswith('save/') or
                r['relative_path'].casefold() in {'debug.log','error.log'})}
            if source_file_set(source)!=expected_source:raise ValueError('SOURCE_FILE_SET_CHANGED')
            font_report={'status':'not_configured'}
            font_settings=meta.get('font_settings') or {}
            from .FontService import alias_runtime_bytes,ALIAS_SCRIPT,ALIAS_TAG
            font_alias_runtime=alias_runtime_bytes(font_settings)
            if font_alias_runtime and meta['engine']!='rpgmaker-mz':raise ValueError('FONT_ALIASES_REQUIRE_MZ')
            known = {r['relative_path'] for r in files}
            if font_alias_runtime and ALIAS_SCRIPT in known:raise ValueError('FONT_ALIAS_SOURCE_CONFLICT')
            if set(changes) - known:
                raise ValueError('UNKNOWN_WRITE_TARGET: missing source record')
            manifest_files = []
            excluded = []
            routes=meta.get('backend_routes',{})
            from .BackendRoutes import route_issues
            invalid_routes=route_issues(routes,(r['relative_path'] for r in files))
            if invalid_routes:
                raise ValueError(invalid_routes[0].code + ': inspect project validation')
            from ModuleFolders.Domain.GameProject.Version import WRITE_PLAN_VERSION,VERSION
            provenance={'source_manifest_sha256':meta.get('source_manifest_hash',''),
                'profile':{'id':meta.get('profile_id',''),'sha256':meta.get('profile_hash','')},
                'engine':meta['engine'],'engine_version':meta.get('engine_version',''),
                'write_plan_version':WRITE_PLAN_VERSION,'application_version':VERSION}
            plan={'algorithm':WRITE_PLAN_VERSION,'source_manifest':meta.get('source_manifest_hash'),
                'dataset_revision':meta['dataset_revision'],'content_revision':meta['content_revision'],
                'profile_hash':meta.get('profile_hash',''),'translations':sorted(translations_digest),
                'font_settings':font_settings,'backend_routes':routes,'image_settings':meta.get('image_settings',{}),
                'font_alias_runtime_sha256':hashlib.sha256(font_alias_runtime).hexdigest() if font_alias_runtime else None,
                'files':files,'test':test,'runtime_capture':runtime_capture}
            plan_digest=hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if journal:
                if plan_digest!=descriptor['plan_digest']:raise ValueError('BUILD_RESUME_PLAN_CHANGED')
            else:
                journal=resources.enter_context(BuildJournal.create(project_root,build_id,{'schema_version':1,'build_id':build_id,
                    'project_id':meta['project_id'],'output_root':str(output_root),'source_root':str(source),
                    'test':bool(test),'runtime_capture':bool(runtime_capture),
                    'frozen_sha256':_frozen_hash(records_root),'plan_digest':plan_digest}))
            attempt_id=journal.new_attempt(control.job_id)
            if resume_build_id:
                from .ProjectLock import JobLease
                for older in self.store.jobs():
                    if older['job_id']==control.job_id or older.get('result',{}).get('build_id')!=build_id:continue
                    if older['run_state'] not in {'RUNNING','PAUSED','PAUSE_REQUESTED','CANCEL_REQUESTED','COMMITTING'}:continue
                    try:
                        with JobLease(project_root,older['job_id']):
                            self.store.update_job(older['job_id'],run_state='INTERRUPTED',error='BUILD_RESUME_OWNER_EXITED')
                    except ValueError as error:
                        if str(error).startswith('PROJECT_BUSY:'):raise ValueError('BUILD_RESUME_ACTIVE_OWNER') from error
                        raise
                for older in journal.attempts():
                    if older['attempt_id']!=attempt_id and older['state']=='RUNNING':
                        journal.finish_attempt(older['attempt_id'],'INTERRUPTED','Explicit resume after owner exit')
            def check_captured_inputs():
                if _frozen_hash(records_root)!=journal.descriptor['frozen_sha256']:raise ValueError('BUILD_FROZEN_SNAPSHOT_CHANGED')
                for captured_record in files:
                    path=captured_record.get('captured_path')
                    if path and file_hash(safe_join(project_root,path,must_exist=True))!=captured_record['sha256']:
                        raise ValueError('SNAPSHOT_HASH_MISMATCH')
                if font_settings and file_hash(safe_join(project_root,font_settings['captured_path'],must_exist=True))!=font_settings['sha256']:
                    raise ValueError('FONT_SNAPSHOT_CHANGED')
                if routes:
                    from .BackendRoutes import fingerprint
                    for route in routes.values():
                        if fingerprint(route['backend_root'])['digest']!=route['fingerprint']['digest']:raise ValueError('BACKEND_SOURCE_CHANGED')
                from .ImageService import build_image
                for relative,replacements in changes.items():
                    if {o.adapter_id for o,_ in replacements}=={'image-region'}:
                        build_image(frozen,relative,safe_join(source,relative,must_exist=True).read_bytes(),project_root)
            # Reused output never bypasses optional backend code or approved-image checks.
            if routes:
                from .BackendRoutes import fingerprint
                for route in routes.values():
                    if fingerprint(route['backend_root'])['digest']!=route['fingerprint']['digest']:
                        raise ValueError('BACKEND_SOURCE_CHANGED')
            if resume_build_id:
                from .ImageService import build_image
                for rel,replacements in changes.items():
                    if {o.adapter_id for o,_ in replacements}=={'image-region'}:
                        build_image(frozen,rel,safe_join(source,rel,must_exist=True).read_bytes(),project_root)
            if font_settings:
                if file_hash(safe_join(project_root,font_settings['captured_path'],must_exist=True))!=font_settings['sha256']:
                    raise ValueError('FONT_SNAPSHOT_CHANGED')
            if published:
                prior=_strict_json((final/'rpg-build-manifest.json').read_bytes())
                if (prior.get('build_id')!=build_id or prior.get('project_id')!=meta['project_id'] or
                    any(prior.get(key)!=value for key,value in provenance.items()) or
                    prior.get('plan_digest')!=plan_digest or prior.get('input_revision')!=meta['content_revision'] or
                    prior.get('mode')!=('test' if test else 'complete') or
                    bool(prior.get('runtime_capture',{}).get('enabled'))!=runtime_capture or
                    Path(prior.get('output_path','')).absolute()!=final):raise ValueError('BUILD_PUBLISHED_INPUT_MISMATCH')
                if not self.verify(final)['passed']:raise ValueError('BUILD_PUBLISHED_OUTPUT_CHANGED')
                required_outputs=set(expected_source)
                if font_settings:required_outputs.add('fonts/'+font_settings['output_file'])
                if font_alias_runtime:required_outputs.add(ALIAS_SCRIPT)
                if runtime_capture:required_outputs.add('js/AiNieeCapture.js')
                prior_files={r['path']:r for r in prior['files']}
                if set(prior_files)!=required_outputs or len(prior['files'])!=len(required_outputs):raise ValueError('BUILD_PUBLISHED_MANIFEST_INCOMPLETE')
                if any(row.get('unit_ids')!=sorted(approved_units.get(rel,())) for rel,row in prior_files.items()):
                    raise ValueError('BUILD_PUBLISHED_UNIT_PROVENANCE_MISMATCH')
                if source_file_set(final)!={r['path'] for r in prior['files']}|{'rpg-build-manifest.json','rpg-build-complete.json'}:
                    raise ValueError('BUILD_PUBLISHED_FILE_SET_CHANGED')
                for record in files:
                    control.check()
                    rel=record['relative_path']
                    if rel.casefold().startswith('save/') or rel.casefold() in {'debug.log','error.log'}:continue
                    if file_hash(safe_join(source,rel,must_exist=True))!=record['sha256']:raise ValueError('SOURCE_CHANGED')
                    previous=prior_files[rel]
                    if previous['original_sha256']!=record['sha256']:raise ValueError('BUILD_PUBLISHED_SOURCE_MISMATCH')
                    captured=record.get('captured_path')
                    original=safe_join(project_root,captured,must_exist=True) if captured else safe_join(source,rel,must_exist=True)
                    if captured and file_hash(original)!=record['sha256']:raise ValueError('SNAPSHOT_HASH_MISMATCH')
                    target=safe_join(final,rel,must_exist=True)
                    if rel=='data/System.json' and font_settings:
                        expected=_strict_json(patch_json(original.read_bytes(),changes.get(rel,[])))
                        expected.setdefault('advanced',{})['mainFontFilename']=font_settings['output_file']
                        valid=_json_canonical(_strict_json(target.read_bytes()))==_json_canonical(expected)
                    elif rel=='index.html' and (runtime_capture or font_alias_runtime):
                        expected=original.read_bytes()+(ALIAS_TAG if font_alias_runtime else b'')
                        if runtime_capture:expected+=b'\n<script src="js/AiNieeCapture.js"></script>\n'
                        valid=target.read_bytes()==expected
                    else:valid=_checkpoint_matches(previous,rel,changes.get(rel),original.read_bytes() if rel in changes else b'',target,routes,meta)
                    if not valid:raise ValueError('BUILD_PUBLISHED_WRITE_PLAN_MISMATCH')
                if font_settings and file_hash(safe_join(final,'fonts/'+font_settings['output_file'],must_exist=True))!=font_settings['sha256']:
                    raise ValueError('BUILD_PUBLISHED_FONT_CHANGED')
                if font_alias_runtime and safe_join(final,ALIAS_SCRIPT,must_exist=True).read_bytes()!=font_alias_runtime:
                    raise ValueError('BUILD_PUBLISHED_FONT_ALIAS_CHANGED')
                if runtime_capture:
                    from .RuntimeCapture import capture_script
                    if safe_join(final,'js/AiNieeCapture.js',must_exist=True).read_bytes()!=capture_script(build_id):
                        raise ValueError('BUILD_PUBLISHED_CAPTURE_CHANGED')
                if source_file_set(source)!=expected_source:raise ValueError('SOURCE_FILE_SET_CHANGED')
                check_captured_inputs()
                begin_commit(self.store,control)
                self.store.record_build(prior);journal.finish_attempt(attempt_id,'COMPLETED','Verified previously published output')
                return dict(prior,recovery_adopted=True)
            from .BuildAtomicWriter import BuildAtomicWriter
            atomic_targets=set(expected_source)|{'rpg-build-manifest.json','rpg-build-complete.json'}
            if font_settings:atomic_targets.add('fonts/'+font_settings['output_file'])
            if font_alias_runtime:atomic_targets.add(ALIAS_SCRIPT)
            if runtime_capture:atomic_targets.add('js/AiNieeCapture.js')
            atomic_writer=BuildAtomicWriter(journal,attempt_id,atomic_targets)
            retained_files.extend(atomic_writer.recover())
            from .StevBuildPipeline import prepare_stev_routes
            stev_prepared=prepare_stev_routes(project_root,source,files,changes,routes,control.check)
            for index, record in enumerate(files):
                control.check()
                rel = record['relative_path']
                if rel.casefold().startswith('save/') or rel.casefold() in {'debug.log', 'error.log'}:
                    excluded.append(rel)
                    continue
                original = safe_join(source, rel, must_exist=True)
                expected = record['sha256']
                if file_hash(original) != expected:
                    raise ValueError(f'SOURCE_CHANGED: {rel}')
                captured = record.get('captured_path')
                input_file = safe_join(project_root, captured, must_exist=True) if captured else original
                if captured and file_hash(input_file)!=expected:raise ValueError(f'SNAPSHOT_HASH_MISMATCH: {rel}')
                target = safe_join(staging, rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                reusable=journal.reusable_file(staging,rel,expected) if resume_build_id else None
                if reusable and not _checkpoint_matches(reusable,rel,changes.get(rel),input_file.read_bytes() if rel in changes else b'',
                        target,routes,meta):reusable=None
                if reusable:
                    manifest_files.append(reusable);resumed_files+=1
                    if progress:progress(index+1,len(files),rel)
                    control.checkpoint('copying',index+1)
                    continue
                if target.exists():retained_files.append(journal.retain_file(staging,rel,attempt_id))
                if resume_build_id and shutil.disk_usage(output_root).free<record['size']+64*1024*1024:
                    raise ValueError('INSUFFICIENT_DISK_SPACE_FOR_RESUME_FILE')
                digest = hashlib.sha256()
                with open(input_file, 'rb') as read, open(target, 'xb') as write:
                    for block in iter(lambda: read.read(1024 * 1024), b''):
                        control.check()
                        write.write(block); digest.update(block)
                    write.flush(); os.fsync(write.fileno())
                if digest.hexdigest() != expected:
                    raise ValueError(f'SNAPSHOT_HASH_MISMATCH: {rel}')
                writer={'id':'copy'}
                if rel in changes:
                    replacements = changes[rel]
                    kinds = {o.adapter_id for o, _ in replacements}
                    if kinds <= {'rpgmaker-native'}:
                        patched = patch_json(target.read_bytes(), replacements)
                        writer={'id':'rpgmaker-native'}
                        if rel in routes:
                            if routes[rel]['backend']=='stev':
                                prepared=stev_prepared.get(rel)
                                if prepared is None:raise ValueError('BACKEND_PROJECT_OUTPUT_MISSING')
                                candidate=Path(prepared['output_path'])
                                candidate=safe_join(project_root,candidate.relative_to(project_root).as_posix(),must_exist=True)
                                actual=candidate.read_bytes()
                                if hashlib.sha256(actual).hexdigest()!=prepared['output_sha256']:
                                    raise ValueError('BACKEND_PROJECT_OUTPUT_CHANGED')
                                if _json_canonical(_strict_json(actual))!=_json_canonical(_strict_json(patched)):
                                    raise ValueError('BACKEND_UNAPPROVED_DIFF')
                                patched=actual;writer=dict(prepared['writer'])
                            else:
                                from .BackendRoutes import routed_write
                                patched,writer=routed_write(project_root,rel,target.read_bytes(),replacements,patched,routes[rel])
                    elif kinds == {'js-literal'}:
                        from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import patch_js
                        patched = patch_js(target.read_bytes(), replacements)
                        writer={'id':'js-literal'}
                        if rel in routes:
                            from .BackendRoutes import routed_write
                            patched,writer=routed_write(project_root,rel,target.read_bytes(),replacements,patched,routes[rel])
                    elif kinds == {'image-region'}:
                        from .ImageService import build_image
                        patched,writer=build_image(frozen,rel,target.read_bytes(),project_root)
                    else:
                        raise ValueError(f'ADAPTER_WRITE_CONFLICT: {rel}: {sorted(kinds)}')
                    atomic_writer.write(target, patched, overwrite=True)
                output_hash=file_hash(target)
                journal.record_file(rel,expected,output_hash,writer)
                manifest_files.append({'path': rel, 'original_sha256': expected,
                    'output_sha256': output_hash, 'changed': output_hash!=expected,'writer':writer})
                if progress:
                    progress(index + 1, len(files), rel)
                control.checkpoint('copying',index+1)
            system_path=safe_join(staging,'data/System.json',must_exist=True)
            system=json.loads(system_path.read_bytes().decode('utf-8-sig'))
            advanced=system.get('advanced',{})
            if font_settings:
                from .FontInspector import inspect_font
                from .FontService import visible_texts
                captured=safe_join(project_root,font_settings['captured_path'],must_exist=True)
                font_bytes=captured.read_bytes()
                if hashlib.sha256(font_bytes).hexdigest()!=font_settings['sha256']:raise ValueError('FONT_SNAPSHOT_CHANGED')
                font_report=inspect_font(captured,visible_texts(frozen,include_source=True))
                if not font_report['passed'] and not test:raise ValueError('FONT_GLYPHS_MISSING')
                destination=safe_join(staging,'fonts/'+font_settings['output_file'])
                if destination.exists() and (not resume_build_id or file_hash(destination)!=font_settings['sha256']):
                    raise ValueError('FONT_OUTPUT_CONFLICT')
                if font_report['sha256']!=font_settings['sha256']:raise ValueError('FONT_SNAPSHOT_CHANGED')
                if not destination.exists():atomic_writer.write(destination,font_bytes)
                advanced['mainFontFilename']=font_settings['output_file']
                system['advanced']=advanced
                atomic_writer.write(system_path,json.dumps(system,ensure_ascii=False,separators=(',',':')).encode(),overwrite=True)
                manifest_files.append({'path':'fonts/'+font_settings['output_file'],'original_sha256':None,
                    'output_sha256':file_hash(destination),'changed':True,'reason':'configured_font'})
                record=next(r for r in manifest_files if r['path']=='data/System.json')
                record.update(output_sha256=file_hash(system_path),changed=True,reason='configured_font')
            elif advanced.get('mainFontFilename'):
                from .FontInspector import inspect_font
                from .FontService import visible_texts
                path=safe_join(staging,'fonts/'+advanced['mainFontFilename'],must_exist=True)
                font_report=inspect_font(path,visible_texts(frozen,include_source=True))
                if not font_report['passed'] and not test:raise ValueError('FONT_GLYPHS_MISSING')
            from .FontService import install_aliases
            font_alias_report=install_aliases(staging,manifest_files,font_settings,writer=atomic_writer.write)
            capture_report={'enabled':False}
            if runtime_capture:
                from .RuntimeCapture import install_capture
                capture_report=install_capture(staging,manifest_files,writer=atomic_writer.write,build_id=build_id)
            payload = {'source_manifest': meta.get('source_manifest_hash'),'plan_digest':plan_digest,
                'dataset_revision': meta['dataset_revision'],
                'content_revision': meta['content_revision'], 'translations': sorted(translations_digest),
                'profile_hash': meta.get('profile_hash', ''),'font_settings':font_settings,
                'backend_routes':{rel:{'backend':r['backend'],'fingerprint':r['fingerprint']['digest']} for rel,r in routes.items()},
                'image_settings':meta.get('image_settings',{}),
                'runtime_capture':capture_report,
                'mode': 'test' if test else 'complete'}
            input_digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            for row in manifest_files:row['unit_ids']=sorted(approved_units.get(row['path'],()))
            manifest = {'schema_version': 1, 'build_id': build_id, 'project_id': meta['project_id'],**provenance,
                'input_revision': meta['content_revision'], 'dataset_revision': meta['dataset_revision'],
                'input_digest': input_digest, 'plan_digest':plan_digest,'target_language': 'zh-CN', 'mode': payload['mode'],
                'text_validation': 'passed', 'runtime_validation': 'not_run',
                'font_validation':font_report,
                'font_aliases':font_alias_report,
                'runtime_capture':capture_report,
                'recovery':{'attempt_id':attempt_id,'resumed':bool(resume_build_id),'reused_files':resumed_files,
                    'retained_files':retained_files},
                'missing_translation_unit_ids': missing, 'excluded_paths': excluded,
                'files': manifest_files, 'output_path': str(final)}
            # Source files are never passed to launch or write routines.
            for record in files:
                control.check()
                rel = record['relative_path']
                if rel in excluded: continue
                if file_hash(safe_join(source, rel, must_exist=True)) != record['sha256']:
                    raise ValueError(f'SOURCE_CHANGED_DURING_BUILD: {rel}')
            if source_file_set(source)!=expected_source:raise ValueError('SOURCE_FILE_SET_CHANGED_DURING_BUILD')
            # Completion metadata from a previous interrupted publish is retained individually.
            for rel in ('rpg-build-manifest.json','rpg-build-complete.json'):
                if (staging/rel).exists():
                    if not resume_build_id:raise ValueError('BUILD_METADATA_OUTPUT_CONFLICT')
                    retained_files.append(journal.retain_file(staging,rel,attempt_id))
            actual_staging={p.relative_to(staging).as_posix() for p in staging.rglob('*') if p.is_file()}
            if actual_staging!={r['path'] for r in manifest_files}:raise ValueError('BUILD_STAGING_FILE_SET_CHANGED')
            check_captured_inputs()
            begin_commit(self.store,control)
            atomic_writer.write(staging / 'rpg-build-manifest.json',
                (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
            write_json(records_root / ('manifest-'+attempt_id+'.json'), manifest)
            if not (records_root/'manifest.json').exists():write_json(records_root/'manifest.json',manifest)
            atomic_writer.write(staging / 'rpg-build-complete.json',
                (json.dumps({'build_id':build_id,'input_digest':input_digest},ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
            if final.exists(): raise FileExistsError(final)
            from .BuildPublication import publish_staging
            publish_staging(staging,final)
            self.store.record_build(manifest)
            journal.finish_attempt(attempt_id,'COMPLETED')
            return manifest
        except Exception as exc:
            if journal and attempt_id:
                from .JobControl import JobCancelled
                journal.finish_attempt(attempt_id,'CANCELLED' if isinstance(exc,JobCancelled) else 'FAILED',str(exc)[:4096])
            failure_path=records_root/('failed-'+(attempt_id or uuid.uuid4().hex)+'.json')
            write_json(failure_path, {'build_id': build_id, 'error': str(exc),
                'staging': str(staging), 'runtime_validation': 'not_run'})
            raise

    @staticmethod
    def verify(output):
        output = Path(output).resolve()
        manifest = json.loads((output / 'rpg-build-manifest.json').read_text(encoding='utf-8'))
        marker = json.loads((output / 'rpg-build-complete.json').read_text(encoding='utf-8'))
        if marker['input_digest'] != manifest['input_digest'] or marker['build_id'] != manifest['build_id']:
            raise ValueError('BUILD_MARKER_MISMATCH')
        failures = [r['path'] for r in manifest['files']
            if file_hash(safe_join(output, r['path'], must_exist=True)) != r['output_sha256']]
        return {'passed': not failures, 'changed_files': failures, 'build_id': manifest['build_id'],
            'runtime_validation': manifest['runtime_validation']}
