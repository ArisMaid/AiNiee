"""Canonical analysis candidates are separate from accepted translations."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import pytest
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from test_game_batch_preparation import create


DATA={'status':'success','characters':[], 'terms':[{'source':'原文','recommended_translation':'源文'}],
      'non_translate':[], 'stats':{'term_count':1}}


def save(store,data=None,**changes):
    meta=store.metadata()
    return store.save_analysis_data(DATA if data is None else data,project_id=meta['project_id'],
        expected_dataset_revision=changes.pop('dataset',meta['dataset_revision']),
        expected_revision=changes.pop('revision',0),**changes)


def model_job(store,**payload):
    meta=store.metadata()
    job=store.create_job('ANALYSIS',{'project_id':meta['project_id'],
        'dataset_revision':meta['dataset_revision'],'analysis_revision':0,
        'request_mode':'analysis',**payload})
    store.update_job(job['job_id'],run_state='RUNNING')
    store.update_job(job['job_id'],run_state='COMMITTING')
    return job['job_id']


def test_analysis_survives_projection_rebuild_without_touching_translations(tmp_path):
    store,units,_=create(tmp_path)
    try:
        before=[store.translation(u.unit_id) for u in units]
        record=save(store)
        assert record['revision']==1 and record['data']==DATA
        assert 'analysis_metadata_v1' in store.metadata()['required_features']
        projection=build_projection(store)
        assert projection.get_extra('analysis_v1')==DATA
        assert projection.get_extra('game_analysis_revision')==1
        record['data']['terms'].clear()
        assert store.analysis_record()['data']==DATA
        assert [store.translation(u.unit_id) for u in units]==before
        assert store.jobs()==[]
    finally:store.close()


@pytest.mark.parametrize('dataset,revision',[(False,0),('1',0),(999,0),(None,0),('current',True),('current','0'),('current',99)])
def test_analysis_rejects_wrong_or_malformed_revision(tmp_path,dataset,revision):
    store,_,_=create(tmp_path)
    try:
        meta=store.metadata()
        with pytest.raises(ValueError):save(store,dataset=meta['dataset_revision'] if dataset=='current' else dataset,revision=revision)
        assert store.metadata()==meta and store.analysis_record()['revision']==0
    finally:store.close()


def test_same_analysis_revision_only_has_one_winner_across_store_instances(tmp_path):
    store,_,_=create(tmp_path)
    root=store.root
    def write(_):
        with ProjectStore(root) as other:
            try:return save(other)['revision']
            except ValueError:return 'conflict'
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,range(2)))
        assert sorted(map(str,results))==['1','conflict']
        assert store.analysis_record()['revision']==1
    finally:store.close()


def test_human_candidate_edit_and_dataset_change_both_refuse_old_analysis_job(tmp_path):
    store,units,_=create(tmp_path)
    try:
        job=model_job(store)
        save(store,{'characters':[],'terms':[],'non_translate':[]})
        with pytest.raises(ValueError,match='ANALYSIS_REVISION_CONFLICT'):save(store,job_id=job)
        assert store.get_job(job)['run_state']=='COMMITTING'
        dataset=store.metadata()['dataset_revision']
        store.replace_units([replace(units[0],source_text='new source',source_hash=''),*units[1:]])
        with pytest.raises(ValueError,match='DATASET_REVISION_CONFLICT'):save(store,dataset=dataset,revision=1)
        assert store.analysis_record()['data']['terms']==[]
    finally:store.close()


def test_model_metadata_and_completed_job_commit_atomically_and_replay_idempotently(tmp_path):
    store,_,_=create(tmp_path)
    try:
        job=model_job(store)
        result=save(store,job_id=job)
        assert result['job_id']==job and result['revision']==1
        assert store.get_job(job)['run_state']=='COMPLETED'
        assert save(store,job_id=job)==result
        with pytest.raises(ValueError):save(store,{'terms':[]},job_id=job)
        assert store.analysis_record()==result
    finally:store.close()


@pytest.mark.parametrize('field,value',[('project_id','other'),('dataset_revision',False),
    ('analysis_revision',True),('request_mode','translate')])
def test_model_cannot_commit_using_a_mismatched_persisted_job(tmp_path,field,value):
    store,_,_=create(tmp_path)
    try:
        job=model_job(store,**{field:value})
        with pytest.raises(ValueError,match='ANALYSIS_JOB_CONTEXT_INVALID'):save(store,job_id=job)
        assert store.analysis_record()['revision']==0
    finally:store.close()


def test_analysis_and_feature_declaration_roll_back_when_job_finish_sql_fails(tmp_path):
    store,_,_=create(tmp_path)
    try:
        job=model_job(store)
        meta=store.metadata()
        with store._write() as sql:
            sql.execute("CREATE TRIGGER fail_analysis_finish BEFORE UPDATE ON jobs WHEN NEW.run_state='COMPLETED' BEGIN SELECT RAISE(ABORT,'injected finish failure'); END")
        with pytest.raises(ValueError):save(store,job_id=job)
        assert store.metadata()==meta and store.analysis_record()['revision']==0
        assert store.get_job(job)['run_state']=='COMMITTING'
    finally:store.close()


def test_analysis_reserved_record_cannot_be_written_through_unversioned_metadata_api(tmp_path):
    store,_,_=create(tmp_path)
    try:
        with pytest.raises(ValueError):store.update_metadata({'analysis_result':{'revision':999,'data':DATA}})
        assert store.analysis_record()['revision']==0
    finally:store.close()
