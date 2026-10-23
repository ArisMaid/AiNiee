"""Application services shared by CLI and desktop UI."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import uuid

from .PathGuard import safe_join, assert_disjoint, atomic_write
from .ProjectStore import ProjectStore
from .BuildService import BuildService, file_hash, write_json
from .TranslationCommitter import TranslationCommitter
from .ProjectLock import project_write
from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Infrastructure.GameAdapters.Registry import AdapterRegistry


class GameProjectService:
    def __init__(self, project):
        self.store = ProjectStore(Path(project).parent if Path(project).is_file() else project)

    def close(self): self.store.close()

    def __enter__(self): return self

    def __exit__(self, *_): self.close()

    @classmethod
    def create(cls, source, project_root, progress=None, on_job=None):
        probe = AdapterRegistry().detect(source)
        if probe is None:
            # Preserve the native detector's specific malformed/unsupported diagnostics.
            from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.Detector import detect_game
            detect_game(source)
            raise ValueError('NO_GAME_ADAPTER')
        source = Path(probe['root']).resolve()
        project_root = Path(project_root).absolute()
        safe_join(project_root, 'project.sqlite3')
        assert_disjoint(source, project_root)
        metadata = dict(probe)
        metadata.update(project_id=uuid.uuid4().hex, source_root=str(source),
            target_language='zh-CN', token_commands=[], token_policy_id='rpgmaker-v2',
            extraction_complete=False)
        with ProjectStore.create(project_root, metadata) as store:
            write_json(safe_join(project_root,'game-project.json'),{'schema_version':store.metadata()['schema_version'],
                'project_id':metadata['project_id'],'engine':probe['engine']})
            from .ProjectLock import ProjectLock
            with ProjectLock(project_root):
                cls._scan_store(store, progress, on_job)
        return cls(project_root)

    @staticmethod
    def _scan_store(store, progress=None, on_job=None):
        from .JobControl import JobControl
        from .JobController import begin_commit
        source = Path(store.metadata()['source_root'])
        job = store.create_job('SCAN')
        store.update_job(job['job_id'], run_state='RUNNING', stage='hashing')
        control = JobControl(store, job['job_id'])
        from .ProjectLock import JobLease
        lease=JobLease(store.root,job['job_id']);lease.__enter__()
        records = []
        known = {r['relative_path']:r for r in store.files()}
        try:
            if on_job:on_job({'job_id':job['job_id'], 'project_root':str(store.root)})
            candidates = []
            for folder, dirs, names in os.walk(source, followlinks=False):
                for name in sorted(dirs):
                    safe_join(source, (Path(folder)/name).relative_to(source).as_posix(), must_exist=True)
                dirs.sort()
                for name in sorted(names):
                    path = Path(folder)/name
                    rel = path.relative_to(source).as_posix()
                    safe_join(source, rel, must_exist=True)
                    candidates.append((rel,path))
            if set(known)-{rel for rel,_ in candidates}:
                raise ValueError('SOURCE_CHANGED: previously scanned files disappeared')
            for i,(rel,path) in enumerate(candidates):
                control.check()
                digest = file_hash(path)
                if rel in known and known[rel]['sha256'] != digest:
                    raise ValueError(f'SOURCE_CHANGED: {rel}')
                record = {'relative_path':rel,'sha256':digest,'size':path.stat().st_size,
                    'encoding':'utf-8' if path.suffix.lower() in {'.js','.json','.html','.css'} else '',
                    'captured_path':'','adapter_id':'rpgmaker-native'}
                if record['encoding']:
                    captured = f'source/{rel}'
                    data = path.read_bytes()
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError(f'SOURCE_CHANGED: {rel}')
                    target = safe_join(store.root,captured)
                    if target.exists():
                        if file_hash(target) != digest:raise ValueError(f'SNAPSHOT_HASH_MISMATCH: {rel}')
                    else:atomic_write(target,data)
                    record['captured_path'] = captured
                store.put_files([record])
                records.append(record)
                if progress:progress(i+1,len(candidates),rel)
                control.checkpoint('hashing',i+1)
            begin_commit(store,control)
            manifest_bytes = json.dumps(records,sort_keys=True,ensure_ascii=False).encode('utf-8')
            manifest = safe_join(store.root,'manifests/source.json')
            if manifest.exists():
                if json.loads(manifest.read_text(encoding='utf-8')) != records:raise ValueError('SOURCE_MANIFEST_CHANGED')
            else:write_json(manifest,records)
            project_file = safe_join(store.root,'game-project.json')
            if not project_file.exists():
                meta=store.metadata()
                write_json(project_file,{'schema_version':meta['schema_version'],'project_id':meta['project_id'],'engine':meta['engine']})
            store.update_metadata({'source_manifest_hash':hashlib.sha256(manifest_bytes).hexdigest(),
                                   'scan_complete':True})
            store.update_job(job['job_id'],run_state='COMPLETED',stage='complete')
        except Exception as exc:
            if next(j for j in store.jobs() if j['job_id']==job['job_id'])['run_state']=='COMMITTING':
                store.update_job(job['job_id'],run_state='FAILED',error=str(exc))
            else:control.fail(exc)
            raise
        finally:lease.__exit__(None,None,None)

    @project_write
    def resume_scan(self, progress=None, on_job=None):
        if self.store.metadata().get('scan_complete'):
            raise ValueError('SCAN_ALREADY_COMPLETE')
        self._scan_store(self.store,progress,on_job)
        return self.summary()

    @project_write
    def extract(self,profile=None,progress=None,on_job=None):
        from .ExtractionService import extract_project
        recovery=extract_project(self.store,profile=profile,progress=progress,on_job=on_job)
        return dict(self.summary(),recovery=recovery)

    @project_write
    def resume_extract(self,job_id,progress=None,on_job=None):
        from .ExtractionService import extract_project
        recovery=extract_project(self.store,progress=progress,on_job=on_job,resume_job_id=job_id)
        return dict(self.summary(),recovery=recovery)

    def summary(self):
        units = self.store.units()
        files = self.store.files()
        translated = sum(bool((t := self.store.translation(u.unit_id)) and t.get('text')
            and not t.get('stale') and t.get('source_hash') == u.source_hash) for u in units)
        meta = self.store.metadata()
        return {'project_id':meta['project_id'], 'project_root':str(self.store.root),
            'engine':meta['engine'], 'engine_version':meta.get('engine_version',''),
            'detection_evidence':meta.get('detection_evidence',{'status':'not_recorded_in_this_project'}),
            'source_file_count':len(files),'source_total_bytes':sum(row['size'] for row in files),
            'unit_count':len(units), 'translated':translated, 'untranslated':len(units)-translated,
            'dataset_revision':meta['dataset_revision'], 'content_revision':meta['content_revision'],
            'extraction_complete':meta.get('extraction_complete',False),
            'stats':dict(meta.get('extraction_stats',{}),unit_count=len(units),
                occurrence_count=sum(len(unit.occurrences) for unit in units)),
            'issue_count':len(self.store.issues())}

    @project_write
    def import_translations(self, rows, origin='manual'):
        committer = TranslationCommitter(self.store)
        results = []
        if isinstance(rows, dict):
            rows = [{'unit_id':key, 'text':value} for key,value in rows.items()]
        if not isinstance(rows,list): raise ValueError('Expected an ID mapping or row list')
        seen = set()
        for row in rows:
            if not isinstance(row,dict) or row.get('unit_id') in seen: raise ValueError('Invalid/duplicate unit row')
            seen.add(row.get('unit_id'))
            unit = self.store.unit(row['unit_id'])
            if unit is None: raise ValueError(f'UNKNOWN_UNIT: {row["unit_id"]}')
            tr = self.store.translation(unit.unit_id) or {}
            proposal = TranslationProposal(unit.unit_id,row['text'],row.get('source_hash',unit.source_hash),
                expected_revision=row.get('expected_revision',tr.get('revision',0)),origin=origin)
            results.append(committer.submit(proposal))
        return results

    def export_translations(self):
        rows = []
        for u in self.store.units():
            tr = self.store.translation(u.unit_id) or {}
            rows.append({'unit_id':u.unit_id,'source_hash':u.source_hash,'kind':u.kind,
                'source_text':u.source_text,'text':tr.get('text','') if not tr.get('stale') else '',
                'stale':tr.get('stale',False),
                'expected_revision':tr.get('revision',0),'manual_locked':tr.get('manual_locked',False),
                'context':u.context,'scene_id':u.scene_id})
        return rows

    def validate(self,progress=None,on_job=None):
        from .ValidationService import inspect_project,validate_project
        if self.store._readonly:return inspect_project(self.store)
        from .ProjectLock import ProjectLock
        with ProjectLock(self.store.root):
            return validate_project(self.store,progress=progress,on_job=on_job)

    @project_write
    def resume_validation(self,job_id,progress=None,on_job=None):
        from .ValidationService import validate_project
        return validate_project(self.store,progress=progress,on_job=on_job,resume_job_id=job_id)

    @project_write
    def build(self, output_root, test=False, progress=None, runtime_capture=False, on_job=None):
        if not self.store.metadata().get('extraction_complete'): raise ValueError('EXTRACTION_INCOMPLETE')
        return BuildService(self.store).build(output_root,test=test,progress=progress,runtime_capture=runtime_capture,on_job=on_job)

    @project_write
    def configure_font(self, path):
        from .FontService import configure_font
        return configure_font(self.store,path)

    @project_write
    def resume_build(self, build_id, progress=None, on_job=None):
        return BuildService(self.store).build(progress=progress,on_job=on_job,resume_build_id=build_id)
