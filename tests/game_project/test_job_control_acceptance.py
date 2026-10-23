import json
from pathlib import Path
import threading
import time
import unittest

import test_adapter_acceptance as fixtures
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.JobControl import JobControl,JobCancelled,request_action
from ModuleFolders.Service.GameProject.JobController import begin_commit
from ModuleFolders.Service.GameProject.BuildService import BuildService,file_hash


class JobControlAcceptance(unittest.TestCase):
    setUp=fixtures.AdapterAcceptance.setUp
    write=fixtures.AdapterAcceptance.write

    def test_cancelled_scan_resumes_captured_files_without_overwrite(self):
        project=self.root.parent/(self.root.name+'-scan-control')
        ids=[]
        def cancel_first(done,total,label):
            if done==1:
                with ProjectStore(project) as other:request_action(other,ids[-1],'cancel')
        with self.assertRaises(JobCancelled):
            GameProjectService.create(self.root,project,progress=cancel_first,on_job=lambda j:ids.append(j['job_id']))
        with GameProjectService(project) as service:
            self.assertFalse(service.store.metadata().get('scan_complete',False))
            self.assertEqual(service.store.jobs()[-1]['run_state'],'CANCELLED')
            captured={r['captured_path']:file_hash(project/r['captured_path']) for r in service.store.files() if r['captured_path']}
            service.resume_scan()
            self.assertTrue(service.store.metadata()['scan_complete'])
            for rel,digest in captured.items():self.assertEqual(file_hash(project/rel),digest)
            service.extract()
            self.assertGreater(service.summary()['unit_count'],0)

    def test_pause_resume_and_cancel_from_another_connection(self):
        project=self.root.parent/(self.root.name+'-pause-control')
        GameProjectService.create(self.root,project).close()
        with ProjectStore(project) as other:
            for action in ['resume','cancel']:
                entered=threading.Event();release=threading.Event();ids=[];errors=[]
                def progress(done,total,label):
                    if not entered.is_set():entered.set();release.wait(3)
                def execute():
                    try:
                        with GameProjectService(project) as service:
                            service.extract(progress=progress,on_job=lambda j:ids.append(j['job_id']))
                    except Exception as exc:errors.append(exc)
                thread=threading.Thread(target=execute);thread.start()
                self.assertTrue(entered.wait(3))
                request_action(other,ids[-1],'pause');release.set()
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    job=next(j for j in other.jobs() if j['job_id']==ids[-1])
                    if job['run_state']=='PAUSED':break
                    time.sleep(.01)
                self.assertEqual(job['run_state'],'PAUSED')
                self.assertTrue(thread.is_alive())
                revision=other.metadata()['dataset_revision']
                request_action(other,ids[-1],action)
                thread.join(4);self.assertFalse(thread.is_alive())
                final=next(j for j in other.jobs() if j['job_id']==ids[-1])
                if action=='resume':self.assertEqual(errors,[]);self.assertEqual(final['run_state'],'COMPLETED')
                else:
                    self.assertIsInstance(errors[0],JobCancelled)
                    self.assertEqual(final['run_state'],'CANCELLED')
                    self.assertEqual(other.metadata()['dataset_revision'],revision)

    def test_cancelled_build_never_publishes_and_commit_is_terminal_for_control(self):
        project=self.root.parent/(self.root.name+'-build-control')
        output=self.root.parent/(self.root.name+'-build-output')
        with GameProjectService.create(self.root,project) as service:
            service.extract();ids=[]
            def cancel_first(done,total,label):
                with ProjectStore(project) as other:request_action(other,ids[-1],'cancel')
            with self.assertRaises(JobCancelled):
                service.build(output,test=True,progress=cancel_first,on_job=lambda j:ids.append(j['job_id']))
            self.assertEqual(list(output.glob('game-zh-CN-*')),[])
            partial=list(output.glob('.staging-*'));self.assertEqual(len(partial),1)
            build=service.build(output,test=True)
            self.assertTrue(BuildService.verify(build['output_path'])['passed'])
            self.assertTrue(partial[0].exists())
            job=service.store.create_job('COMMIT_TEST');service.store.update_job(job['job_id'],run_state='RUNNING')
            begin_commit(service.store,JobControl(service.store,job['job_id']))
            with self.assertRaisesRegex(ValueError,'REFUSED'):request_action(service.store,job['job_id'],'cancel')
            service.store.update_job(job['job_id'],run_state='COMPLETED')

    def test_recovery_does_not_interrupt_an_active_model_request_lease(self):
        from ModuleFolders.Service.GameProject.ProjectLock import JobLease
        from ModuleFolders.Service.GameProject.JobController import recover_jobs
        project=self.root.parent/(self.root.name+'-lease')
        with GameProjectService.create(self.root,project) as service:
            job=service.store.create_job('TRANSLATE')
            service.store.update_job(job['job_id'],run_state='RUNNING')
            with JobLease(project,job['job_id']):
                result=recover_jobs(service.store)
                self.assertEqual(result['interrupted_jobs'],[])
                self.assertEqual(result['active_jobs'],[job['job_id']])
            self.assertEqual(recover_jobs(service.store)['interrupted_jobs'],[job['job_id']])
            paused=service.store.create_job('PAUSED_CRASH')
            service.store.update_job(paused['job_id'],run_state='RUNNING')
            service.store.update_job(paused['job_id'],run_state='PAUSED')
            with self.assertRaisesRegex(ValueError,'OWNER_MISSING'):
                request_action(service.store,paused['job_id'],'resume')
            self.assertEqual(recover_jobs(service.store)['interrupted_jobs'],[paused['job_id']])
