"""Codex-owned coverage reports must obey snapshot/job publication boundaries."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from test_external_tasks import project
from ModuleFolders.Service.GameProject.JobControl import JobCancelled,request_action
from ModuleFolders.Service.GameProject.BuildService import file_hash

ROOT=Path(__file__).resolve().parents[2]
BACKENDS={'stev':ROOT/'StevExtraction','rpgmtl':ROOT/'work/vendor/RPGMTL','sextractor':ROOT/'work/vendor/SExtractor'}


@pytest.mark.parametrize('backend',list(BACKENDS))
def test_actual_comparison_persists_reference_report_without_writes(project,backend):
    from ModuleFolders.Service.GameProject.BackendComparisonService import compare_backend
    if not BACKENDS[backend].is_dir():pytest.skip('Optional pinned backend not installed')
    store=project.store;before=store.metadata();units=[u.to_dict() for u in store.units()]
    result=compare_backend(store,backend,BACKENDS[backend],'data/Items.json')
    assert result['reference_only'] and result['writes_enabled'] is False
    assert result['counts']['native_total']>0 and result['counts']['backend_total']>0
    assert result['source_sha256']==file_hash(Path(before['source_root'])/'data/Items.json')
    saved=json.loads(Path(result['report_path']).read_text(encoding='utf-8'))
    assert saved['counts']==result['counts'] and saved['dataset_revision']==before['dataset_revision']
    assert saved['job_id']==result['job_id']
    assert [u.to_dict() for u in store.units()]==units
    assert store.metadata().get('backend_routes',{})==before.get('backend_routes',{})
    assert store.metadata()['content_revision']==before['content_revision']
    job=store.jobs()[-1]
    assert job['job_id']==result['job_id'] and job['operation']=='BACKEND_COMPARE' and job['run_state']=='COMPLETED'


def test_cancel_before_dispatch_never_calls_backend_or_publishes_report(project):
    from ModuleFolders.Service.GameProject.BackendComparisonService import compare_backend
    with patch('ModuleFolders.Service.GameProject.BackendComparisonService.extract_document') as worker:
        with pytest.raises(JobCancelled):
            compare_backend(project.store,'stev',BACKENDS['stev'],'data/Items.json',
                on_job=lambda j:request_action(project.store,j['job_id'],'cancel'))
    worker.assert_not_called()
    assert project.store.jobs()[-1]['run_state']=='CANCELLED'
    assert not list((project.store.root/'work/comparisons').glob('*'))


def test_late_dataset_change_refuses_report(project):
    from ModuleFolders.Service.GameProject.BackendComparisonService import compare_backend
    def extract(*args):
        # An identical set is deliberately a no-op. Change the dataset to
        # exercise the stale-input guard rather than merely calling its API.
        current=project.store.units()
        project.store.replace_units(current[:-1])
        return {'ok':True,'records':[],'capabilities':{}}
    with patch('ModuleFolders.Service.GameProject.BackendComparisonService.extract_document',side_effect=extract):
        with pytest.raises(ValueError,match='BACKEND_COMPARE_INPUT_CHANGED'):
            compare_backend(project.store,'stev',BACKENDS['stev'],'data/Items.json')
    assert project.store.jobs()[-1]['run_state']=='FAILED'
    assert not list((project.store.root/'work/comparisons').glob('*'))


def test_cancel_after_worker_before_report_preserves_existing_data(project):
    from ModuleFolders.Service.GameProject.BackendComparisonService import compare_backend
    ids=[];before=project.store.metadata()['dataset_revision']
    def extract(*args):
        request_action(project.store,ids[0],'cancel')
        return {'ok':True,'records':[],'capabilities':{}}
    with patch('ModuleFolders.Service.GameProject.BackendComparisonService.extract_document',side_effect=extract):
        with pytest.raises(JobCancelled):
            compare_backend(project.store,'stev',BACKENDS['stev'],'data/Items.json',on_job=lambda j:ids.append(j['job_id']))
    assert project.store.jobs()[-1]['run_state']=='CANCELLED'
    assert project.store.metadata()['dataset_revision']==before
    assert not list((project.store.root/'work/comparisons').glob('*'))


def test_changed_capture_is_rejected_before_backend(project):
    from ModuleFolders.Service.GameProject.BackendComparisonService import compare_backend
    record=next(r for r in project.store.files() if r['relative_path']=='data/Items.json')
    (project.store.root/record['captured_path']).write_bytes(b'[]')
    with patch('ModuleFolders.Service.GameProject.BackendComparisonService.extract_document') as worker:
        with pytest.raises(ValueError,match='BACKEND_COMPARE_SNAPSHOT_CHANGED'):
            compare_backend(project.store,'stev',BACKENDS['stev'],'data/Items.json')
    worker.assert_not_called()
    assert project.store.jobs()[-1]['run_state']=='FAILED'
