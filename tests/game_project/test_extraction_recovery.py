"""Persistent per-document results, atomic publication and real process exits."""
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
import test_adapter_acceptance as fixtures
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker import JsonExtractor
from ModuleFolders.Infrastructure.GameAdapters.JsWorker import JsBridge
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.JobControl import JobCancelled,request_action
from ModuleFolders.Service.GameProject.JobController import recover_jobs
from ModuleFolders.Service.GameProject.BuildService import file_hash


@pytest.fixture
def extraction_case():
    fixture=fixtures.AdapterAcceptance();fixture.setUp();root=fixture.root
    (root/'js/words.js').write_bytes(b'\xef\xbb\xbf'+
        "// 😀前置\r\nconst Root={words:{save:'保存'}};const Extra={other:'設定'};\r\n".encode('utf-8'))
    profile={'schema_version':1,'id':'checkpoint-test','engine':'rpgmaker-mz','json_rules':[],
        'js_rules':[{'id':'words','file':'js/words.js','object_path':'Root.words','evidence_status':'verified'},
            {'id':'other','file':'js/words.js','object_path':'Extra','evidence_status':'verified'},
            {'id':'pending','file':'js/words.js','object_path':'Pending','evidence_status':'pending'}]}
    with GameProjectService.create(root,root.parent/(root.name+'-extract-resume')) as service:
        yield service,root,profile


def cancel_at(service,profile,count):
    ids=[]
    def cancel(done,total,label):
        if done==count:
            with ProjectStore(service.store.root) as other:request_action(other,ids[-1],'cancel')
    with pytest.raises(JobCancelled):
        service.extract(profile,progress=cancel,on_job=lambda j:ids.append(j['job_id']))
    return ids[-1]


def seed_accepted(service,profile):
    service.extract(profile)
    unit=next(u for u in service.store.units() if u.source_text=='保存')
    assert service.import_translations({unit.unit_id:'存档'})[0].status=='accepted'
    service.store.set_locked(unit.unit_id,True)
    return unit


def test_cancel_preserves_dataset_and_manual_edits_remain_when_resuming(extraction_case):
    service,root,profile=extraction_case;locked=seed_accepted(service,profile)
    metadata=service.store.metadata();units=[asdict(u) for u in service.store.units()]
    old=cancel_at(service,profile,2)
    assert service.store.metadata()==metadata and [asdict(u) for u in service.store.units()]==units
    assert service.store.jobs()[-1]['run_state']=='CANCELLED'
    editable=next(u for u in service.store.units() if u.source_text=='回復薬')
    assert service.import_translations({editable.unit_id:'中断期间人工新稿'})[0].status=='accepted'
    service.store.set_locked(editable.unit_id,True)
    before={u.unit_id:service.store.translation(u.unit_id) for u in (locked,editable)}
    with patch.object(JsonExtractor,'extract_document',wraps=JsonExtractor.extract_document) as parsed:
        result=service.resume_extract(old)
        assert parsed.call_count==2
    assert result['recovery']['reused_json_files']==2 and result['recovery']['reused_js_rules']==0
    assert {uid:service.store.translation(uid) for uid in before}==before
    assert service.store.jobs()[-1]['run_state']=='COMPLETED'
    assert service.store.jobs()[-1]['result']['committed_dataset_revision']==service.store.metadata()['dataset_revision']


def test_all_json_and_js_results_are_reused_without_parser_or_node(extraction_case):
    service,root,profile=extraction_case
    old=cancel_at(service,profile,6)
    assert not service.store.metadata()['extraction_complete'] and service.store.units()==[]
    with patch.object(JsonExtractor,'extract_document',side_effect=AssertionError('JSON reparse')):
        with patch.object(JsBridge,'_call',side_effect=AssertionError('Node reparse')):
            result=service.resume_extract(old)
    assert result['recovery']['reused_json_files']==4 and result['recovery']['reused_js_rules']==2
    assert result['extraction_complete'] and service.validate()['passed']
    assert len([i for i in service.store.issues() if i['code']=='PROFILE_UNVERIFIED'])==1


def test_newer_extraction_invalidates_old_checkpoint(extraction_case):
    service,root,profile=extraction_case
    seed_accepted(service,profile);old=cancel_at(service,profile,1)
    service.extract(dict(profile,id='newer-profile'))
    before=service.store.metadata();count=len(service.store.jobs())
    with pytest.raises(ValueError,match='EXTRACTION_RESUME_INPUT_CHANGED'):service.resume_extract(old)
    assert service.store.metadata()==before and len(service.store.jobs())==count


def test_snapshot_or_cached_blob_corruption_never_publishes(extraction_case):
    service,root,profile=extraction_case
    old=cancel_at(service,profile,1)
    job=next(j for j in service.store.jobs() if j['job_id']==old)
    records=service.store.root/'extractions'/job['result']['extraction_id']
    blob=next((records/'results').glob('*.json'));blob.write_bytes(b'corrupted cache')
    corrupted=file_hash(blob)
    with pytest.raises(ValueError,match='EXTRACTION_CHECKPOINT_CORRUPT'):service.resume_extract(old)
    assert service.store.units()==[] and not service.store.metadata()['extraction_complete']
    assert file_hash(blob)==corrupted
    other=cancel_at(service,profile,1)
    original=file_hash(root/'data/Items.json');snapshot=service.store.root/'source/data/Items.json'
    with snapshot.open('ab') as stream:stream.write(b' ')
    with pytest.raises(ValueError,match='SNAPSHOT_HASH_MISMATCH'):service.resume_extract(other)
    assert file_hash(root/'data/Items.json')==original
    assert service.store.units()==[]


def test_failed_atomic_issue_write_rolls_back_dataset_metadata_and_completion(extraction_case):
    service,root,profile=extraction_case
    locked=seed_accepted(service,profile)
    before_meta=service.store.metadata();before_units=[asdict(u) for u in service.store.units()]
    before_tr=service.store.translation(locked.unit_id);before_issues=service.store.issues()
    module=importlib.import_module('ModuleFolders.Service.GameProject.ProjectStore')
    with patch.object(module,'_insert_issues',side_effect=OSError('injected final issue failure')):
        with pytest.raises(OSError,match='injected final issue failure'):service.extract(profile)
    failed=service.store.jobs()[-1];assert failed['run_state']=='FAILED'
    assert service.store.metadata()==before_meta
    assert [asdict(u) for u in service.store.units()]==before_units
    assert service.store.translation(locked.unit_id)==before_tr and service.store.issues()==before_issues
    with patch.object(JsonExtractor,'extract_document',side_effect=AssertionError('cached JSON was parsed again')):
        with patch.object(JsBridge,'_call',side_effect=AssertionError('cached JS was parsed again')):
            recovered=service.resume_extract(failed['job_id'])
    assert recovered['recovery']['reused_json_files']==4 and recovered['recovery']['reused_js_rules']==2
    assert service.store.translation(locked.unit_id)==before_tr


def child(service,profile,code):
    return subprocess.run([sys.executable,'-c',code,str(service.store.root),json.dumps(profile)],
        cwd=Path(__file__).resolve().parents[2],capture_output=True,timeout=20)


def test_real_process_exit_recovers_committed_document_without_partial_dataset(extraction_case):
    service,root,profile=extraction_case;locked=seed_accepted(service,profile)
    tr=service.store.translation(locked.unit_id);meta=service.store.metadata()
    run=child(service,profile,'''import os,sys,json
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
with GameProjectService(sys.argv[1]) as service:
    service.extract(json.loads(sys.argv[2]),progress=lambda done,total,label:os._exit(41) if done==1 else None)
''')
    assert run.returncode==41,run.stderr
    previous=service.store.jobs()[-1];assert previous['run_state']=='RUNNING'
    assert service.store.metadata()==meta
    assert previous['job_id'] in recover_jobs(service.store)['interrupted_jobs']
    result=service.resume_extract(previous['job_id'])
    assert result['recovery']['reused_json_files']==1
    assert service.store.translation(locked.unit_id)==tr


def test_real_exit_after_commit_keeps_complete_dataset_and_job_together(extraction_case):
    service,root,profile=extraction_case
    run=child(service,profile,'''import os,sys,json
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
actual=ProjectStore.replace_units
def commit_then_exit(self,*args,**kwargs):
    result=actual(self,*args,**kwargs)
    if kwargs.get('extraction_completion'):os._exit(42)
    return result
ProjectStore.replace_units=commit_then_exit
with GameProjectService(sys.argv[1]) as service:service.extract(json.loads(sys.argv[2]))
''')
    assert run.returncode==42,run.stderr
    job=service.store.jobs()[-1]
    assert job['run_state']=='COMPLETED'
    assert service.store.metadata()['extraction_complete'] and len(service.store.units())>0
    assert job['job_id'] not in recover_jobs(service.store)['interrupted_jobs']
    with pytest.raises(ValueError,match='EXTRACTION_NOT_RESUMABLE'):service.resume_extract(job['job_id'])


def test_atomic_completion_requires_committing_extraction_job(extraction_case):
    service,root,profile=extraction_case
    job=service.store.create_job('EXTRACT');service.store.update_job(job['job_id'],run_state='RUNNING')
    before=service.store.metadata()
    with pytest.raises(ValueError,match='must be COMMITTING'):
        service.store.replace_units([],extraction_metadata={'extraction_complete':True},
            extraction_completion={'job_id':job['job_id'],'checkpoint':0,'result':{}})
    assert service.store.metadata()==before and service.store.units()==[]
