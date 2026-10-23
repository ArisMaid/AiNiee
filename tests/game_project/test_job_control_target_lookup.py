from unittest.mock import patch
import pytest
from test_external_tasks import project
from ModuleFolders.Service.GameProject.JobControl import JobControl, JobCancelled, request_action


def test_control_never_reads_unrelated_large_historical_results(project):
    store = project.store
    historical = store.create_job('HISTORICAL', {})
    store.update_job(historical['job_id'], run_state='RUNNING')
    store.update_job(historical['job_id'], run_state='COMMITTING')
    store.update_job(historical['job_id'], run_state='COMPLETED', result={'large': 'x' * (2 * 1024 * 1024)})
    target = store.create_job('CURRENT', {})
    store.update_job(target['job_id'], run_state='RUNNING')
    with patch.object(store, 'jobs', side_effect=AssertionError('control must not enumerate historical results')):
        assert store.get_job('not-present') is None
        JobControl(store, target['job_id']).check(force=True)
        request_action(store, target['job_id'], 'cancel')
        with pytest.raises(JobCancelled):
            JobControl(store, target['job_id']).check(force=True)
        assert store.get_job(target['job_id'])['run_state'] == 'CANCELLED'
    assert len(store.get_job(historical['job_id'])['result']['large']) == 2 * 1024 * 1024
