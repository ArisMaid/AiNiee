"""Independent interruption/recovery tests; every private fixture is retained."""
from pathlib import Path
import json,hashlib
import os,subprocess,sys
import uuid
import unittest
from unittest.mock import patch
import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.BuildService import BuildService,file_hash
from ModuleFolders.Service.GameProject.BuildJournal import BuildJournal


class BuildResumeAcceptance(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def project(self):
        return GameProjectService.create(self.root,self.root.parent/(self.root.name+'-resume-project'))

    def fail_after_two_files(self,service,**kwargs):
        def progress(done,total,rel):
            if done==2:raise OSError('injected interruption after two verified files')
        with self.assertRaisesRegex(OSError,'injected interruption'):
            service.build(self.root.parent/(self.root.name+'-resume-output'),test=True,progress=progress,**kwargs)
        job=next(j for j in reversed(service.store.jobs()) if j['operation']=='BUILD')
        self.assertEqual(job['run_state'],'FAILED')
        return job['result']['build_id'],Path(job['result']['staging'])

    def test_resume_reuses_files_retains_corruption_and_keeps_frozen_translations(self):
        with self.project() as service:
            service.extract();unit=next(u for u in service.store.units() if u.source_text=='学校')
            service.import_translations({unit.unit_id:'学校甲'})
            build_id,staging=self.fail_after_two_files(service)
            with BuildJournal.open(service.store.root,build_id) as journal:records=journal.records()
            self.assertEqual(len(records),2)
            corrupted=staging/records[0]['path'];corrupted.write_bytes(b'corrupted output')
            service.import_translations({unit.unit_id:'学校乙'});service.store.set_locked(unit.unit_id,True)
            build=service.resume_build(build_id)
            self.assertTrue(BuildService.verify(build['output_path'])['passed'])
            self.assertGreaterEqual(build['recovery']['reused_files'],1)
            retained=build['recovery']['retained_files'];self.assertGreaterEqual(len(retained),1)
            self.assertEqual((service.store.root/retained[0]).read_bytes(),b'corrupted output')
            output=json.loads((Path(build['output_path'])/'data/Map001.json').read_text(encoding='utf-8'))
            self.assertEqual(output['displayName'],'学校甲')
            self.assertEqual(service.store.translation(unit.unit_id)['text'],'学校乙')
            self.assertTrue(service.store.translation(unit.unit_id)['manual_locked'])
            adopted=service.resume_build(build_id)
            self.assertTrue(adopted['recovery_adopted']);self.assertEqual(adopted['input_digest'],build['input_digest'])

    def test_recorded_hash_cannot_override_frozen_write_plan(self):
        with self.project() as service:
            service.extract();build_id,staging=self.fail_after_two_files(service)
            with BuildJournal.open(service.store.root,build_id) as journal:
                row=journal.records()[0];path=staging/row['path'];path.write_bytes(b'changed program bytes')
                journal.record_file(row['path'],row['original_sha256'],file_hash(path),{'id':'copy'})
            build=service.resume_build(build_id)
            self.assertEqual(file_hash(Path(build['output_path'])/row['path']),row['original_sha256'])
            self.assertTrue(build['recovery']['retained_files'])

    def test_changed_source_and_frozen_snapshot_are_rejected(self):
        with self.project() as service:
            service.extract();build_id,staging=self.fail_after_two_files(service)
            original=(self.root/'index.html').read_bytes();(self.root/'index.html').write_bytes(original+b'changed')
            with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):service.resume_build(build_id)
            (self.root/'index.html').write_bytes(original)
            frozen=service.store.root/'builds'/build_id/'project.sqlite3'
            with frozen.open('ab') as f:f.write(b'changed snapshot bytes')
            with self.assertRaisesRegex(ValueError,'BUILD_FROZEN_SNAPSHOT_CHANGED'):service.resume_build(build_id)

    def test_unknown_staging_file_never_published(self):
        with self.project() as service:
            service.extract();build_id,staging=self.fail_after_two_files(service)
            (staging/'unapproved.txt').write_text('unexpected file',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'BUILD_STAGING_FILE_SET_CHANGED'):service.resume_build(build_id)
            self.assertFalse((staging.parent/('game-zh-CN-'+build_id)).exists())

    def test_resume_after_capture_installation_failure(self):
        with self.project() as service:
            service.extract()
            with patch('ModuleFolders.Service.GameProject.JobController.begin_commit',side_effect=OSError('injected publish failure')):
                with self.assertRaisesRegex(OSError,'injected publish failure'):
                    service.build(self.root.parent/(self.root.name+'-capture-resume'),test=True,runtime_capture=True)
            job=next(j for j in reversed(service.store.jobs()) if j['operation']=='BUILD')
            build=service.resume_build(job['result']['build_id'])
            self.assertTrue(BuildService.verify(build['output_path'])['passed'])
            index=(Path(build['output_path'])/'index.html').read_bytes()
            self.assertEqual(index.count(b'<script src="js/AiNieeCapture.js">'),1)

    def test_real_process_exit_recovers_leases_and_attempt_history(self):
        with self.project() as service:
            service.extract()
            script=service.store.root/'crash-builder.py'
            script.write_text('import os,sys\nfrom ModuleFolders.Service.GameProject.GameProjectService import GameProjectService\n'
                'def step(done,total,rel):\n    if done==2:os._exit(17)\n'
                'with GameProjectService(sys.argv[1]) as service:service.build(sys.argv[2],test=True,progress=step)\n',encoding='utf-8')
            env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[2]);env['AINIEE_OFFLINE']='1'
            child=subprocess.run([sys.executable,str(script),str(service.store.root),str(self.root.parent/(self.root.name+'-crash-output'))],
                cwd=Path(__file__).resolve().parents[2],env=env,capture_output=True,timeout=20)
            self.assertEqual(child.returncode,17,child.stderr.decode('utf-8','replace'))
            old=next(j for j in reversed(service.store.jobs()) if j['operation']=='BUILD')
            self.assertEqual(old['run_state'],'RUNNING')
            build_id=old['result']['build_id'];build=service.resume_build(build_id)
            self.assertTrue(BuildService.verify(build['output_path'])['passed'])
            self.assertGreaterEqual(build['recovery']['reused_files'],2)
            recovered=next(j for j in service.store.jobs() if j['job_id']==old['job_id'])
            self.assertEqual(recovered['run_state'],'INTERRUPTED')
            with BuildJournal.open(service.store.root,build_id) as journal:
                self.assertEqual([a['state'] for a in journal.attempts()],['INTERRUPTED','COMPLETED'])

    def test_journal_boundaries_and_existing_record_are_not_overwritten(self):
        project=self.root.parent/(self.root.name+'-journal');project.mkdir()
        build_id=uuid.uuid4().hex;records=project/'builds'/build_id;records.mkdir(parents=True)
        output=self.root.parent/(self.root.name+'-journal-output');staging=output/('.staging-'+build_id);staging.mkdir(parents=True)
        descriptor={'schema_version':1,'build_id':build_id,'project_id':'fixture','output_root':str(output),
            'source_root':str(self.root),'test':True,'runtime_capture':False,'frozen_sha256':'a'*64,'plan_digest':'b'*64}
        with BuildJournal.create(project,build_id,descriptor) as journal:
            attempt=journal.new_attempt(uuid.uuid4().hex)
            path=staging/'test.txt';path.write_bytes(b'original')
            journal.record_file('test.txt',file_hash(path),file_hash(path),{'id':'copy'})
            with self.assertRaises(ValueError):journal.record_file('TEST.txt','a'*64,'b'*64,{'id':'copy'})
            with self.assertRaises(ValueError):journal.record_file('../escape.txt','a'*64,'b'*64,{'id':'copy'})
            with self.assertRaises(ValueError):journal.record_file('other.txt','a'*64,'b'*64,{'id':'copy','invalid':float('nan')})
            with self.assertRaises(ValueError):journal.reusable_file(output,'test.txt',file_hash(path))
            with self.assertRaises(ValueError):journal.retain_file(staging,'../outside',attempt)
            journal.finish_attempt(attempt,'FAILED','fixture')
            with self.assertRaises(ValueError):journal.finish_attempt(attempt,'COMPLETED')
        before=file_hash(records/'resume.sqlite3')
        with self.assertRaises(FileExistsError):BuildJournal.create(project,build_id,descriptor)
        self.assertEqual(file_hash(records/'resume.sqlite3'),before)
        missing=uuid.uuid4().hex;(project/'builds'/missing).mkdir()
        with self.assertRaises(FileNotFoundError):BuildJournal.open(project,missing)
        self.assertFalse((project/'builds'/missing/'resume.sqlite3').exists())

    def test_published_output_must_still_match_frozen_write_plan(self):
        with self.project() as service:
            service.extract();build=service.build(self.root.parent/(self.root.name+'-published-check'),test=True)
            root=Path(build['output_path']);target=root/'data/Items.json';target.write_bytes(b'[null]')
            manifest_path=root/'rpg-build-manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            row=next(r for r in manifest['files'] if r['path']=='data/Items.json');row['output_sha256']=file_hash(target)
            manifest_path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
            self.assertTrue(BuildService.verify(root)['passed'])
            with self.assertRaisesRegex(ValueError,'BUILD_PUBLISHED_WRITE_PLAN_MISMATCH'):service.resume_build(build['build_id'])
            self.assertEqual(target.read_bytes(),b'[null]')

    def test_cancelled_build_requires_explicit_resume_and_retains_attempt(self):
        from ModuleFolders.Service.GameProject.JobControl import request_action,JobCancelled
        with self.project() as service:
            service.extract();holder={}
            def started(info):holder.update(info)
            def progress(done,total,rel):
                if done==2:request_action(service.store,holder['job_id'],'cancel')
            with self.assertRaises(JobCancelled):
                service.build(self.root.parent/(self.root.name+'-cancel-resume'),test=True,progress=progress,on_job=started)
            job=next(j for j in service.store.jobs() if j['job_id']==holder['job_id'])
            self.assertEqual(job['run_state'],'CANCELLED')
            build=service.resume_build(job['result']['build_id'])
            self.assertTrue(BuildService.verify(build['output_path'])['passed'])
            with BuildJournal.open(service.store.root,build['build_id']) as journal:
                self.assertEqual([a['state'] for a in journal.attempts()],['CANCELLED','COMPLETED'])


if __name__=='__main__':unittest.main()
