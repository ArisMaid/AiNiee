"""Local execution ownership is separate from persisted request job identity."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from ModuleFolders.Service.GameProject.GameTaskScope import (
    GameTaskCoordinator,GameTaskScope,coordinator_for,event_matches_current,game_task_progress)
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.Cache.CacheProject import CacheProject
from test_game_batch_preparation import create


def setup_scope(tmp_path,operation='translate'):
    store,units,_=create(tmp_path)
    project=build_projection(store)
    coordinator=GameTaskCoordinator()
    scope=coordinator.reserve(project,operation)
    return store,units,project,coordinator,scope


def test_scope_payload_is_detached_and_never_invents_a_request_job(tmp_path):
    store,_,project,coordinator,scope=setup_scope(tmp_path)
    try:
        assert scope.dataset_revision==store.metadata()['dataset_revision']
        scope.validate_canonical(project)
        first=scope.payload();first['project_id']='tampered'
        assert not scope.matches(project,first) and scope.matches(project,scope.payload())
        assert 'job_id' not in scope.payload() and coordinator.job_ids(scope)==()
        assert store.jobs()==[] and len(scope.execution_id)==32
        assert scope.execution_id not in project.extra.values()
    finally:store.close()


@pytest.mark.parametrize('field,value',[('game_project_root','foreign-root'),('project_id','foreign'),
    ('dataset_revision',True),('dataset_revision',999),('game_execution_id','old-run')])
def test_start_requires_the_exact_reserved_scope_without_consuming_it(tmp_path,field,value):
    store,_,project,coordinator,scope=setup_scope(tmp_path)
    try:
        wrong={**scope.payload(),field:value}
        with pytest.raises(ValueError,match='START_CONTEXT_INVALID'):coordinator.accept(project,wrong)
        assert coordinator.accept(project,scope.payload()) is scope
        with pytest.raises(ValueError,match='ALREADY_ACTIVE'):coordinator.reserve(project,'translate')
        with pytest.raises(ValueError,match='START_CONTEXT_INVALID'):coordinator.accept(project,scope.payload())
    finally:store.close()


def test_concurrent_reservation_claims_only_one_execution(tmp_path):
    store,_,_=create(tmp_path);project=build_projection(store);coordinator=GameTaskCoordinator()
    def reserve():
        try:return coordinator.reserve(project,'translate')
        except ValueError as error:return str(error)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:reserve(),range(2)))
        assert sum(isinstance(result,GameTaskScope) for result in results)==1
        assert sum('ALREADY_ACTIVE' in result for result in results if isinstance(result,str))==1
    finally:store.close()


def test_terminal_done_is_consumed_once_and_old_events_cannot_finish_a_new_run(tmp_path):
    store,_,project,coordinator,old=setup_scope(tmp_path)
    try:
        coordinator.accept(project,old.payload())
        assert not coordinator.consume_done(project,old.payload())
        assert coordinator.finish(old) and not coordinator.active
        assert coordinator.consume_done(project,old.payload())
        assert not coordinator.consume_done(project,old.payload())
        assert coordinator.event_matches(project,old.payload())  # queued final monitor data
        new=coordinator.reserve(project,'polish');coordinator.accept(project,new.payload())
        assert not coordinator.event_matches(project,old.payload())
        assert not coordinator.finish(old) and coordinator.active
        assert not coordinator.request_stop(project,old.payload())
        assert coordinator.request_stop(project,new.payload())
        assert coordinator.finish(new) and coordinator.consume_done(project,new.payload())
    finally:store.close()


def test_projection_replacement_and_canonical_dataset_drift_are_distinct(tmp_path):
    store,units,project,coordinator,scope=setup_scope(tmp_path)
    try:
        replacement=build_projection(store)
        assert not scope.matches(replacement,scope.payload())
        with pytest.raises(ValueError,match='PROJECT_CHANGED'):scope.validate_canonical(replacement)
        store.replace_units([replace(units[0],source_text='changed',source_hash=''),*units[1:]])
        assert scope.matches(project,scope.payload())  # cached identity alone is insufficient
        with pytest.raises(ValueError,match='DATASET_REVISION_CONFLICT'):scope.validate_canonical(project)
    finally:store.close()


@pytest.mark.parametrize('dataset',[None,True,'1',-1])
def test_old_or_malformed_projection_requires_reload_before_reservation(tmp_path,dataset):
    store,_,project,_,_=setup_scope(tmp_path)
    try:
        project.extra['game_dataset_revision']=dataset
        with pytest.raises(ValueError,match='REFRESH_REQUIRED'):GameTaskCoordinator().reserve(project,'translate')
    finally:store.close()


def test_real_job_identity_is_bound_only_to_its_own_running_execution(tmp_path):
    store,_,project,coordinator,scope=setup_scope(tmp_path)
    try:
        coordinator.accept(project,scope.payload())
        job=store.create_job('TRANSLATE',{'game_execution_id':scope.execution_id,'dataset_revision':scope.dataset_revision})
        info=scope.payload(job_id=job['job_id'])
        coordinator.bind_job(scope,project,info)
        assert coordinator.job_ids(scope)==(job['job_id'],)
        with pytest.raises(ValueError,match='JOB_CONTEXT_INVALID'):
            coordinator.bind_job(scope,project,{**info,'game_execution_id':'old'})
        assert coordinator.request_stop(project,scope.payload())
        with pytest.raises(ValueError,match='STOP_REQUESTED'):coordinator.bind_job(scope,project,info)
    finally:store.close()


def test_manager_local_scope_does_not_affect_other_managers_or_ordinary_events(tmp_path):
    store,_,_=create(tmp_path);project=build_projection(store)
    first=SimpleNamespace(project=project);second=SimpleNamespace(project=project)
    try:
        coordinator=coordinator_for(first);scope=coordinator.reserve(project,'translate')
        assert coordinator_for(first) is coordinator and coordinator_for(second) is not coordinator
        assert event_matches_current(first,scope.payload()) and not event_matches_current(second,scope.payload())
        ordinary=SimpleNamespace(project=CacheProject(project_type='Txt'))
        assert event_matches_current(ordinary,{}) and not event_matches_current(ordinary,scope.payload())
    finally:store.close()


def test_request_scope_recheck_does_not_rescan_whole_projection(tmp_path):
    store,_,project,_,scope=setup_scope(tmp_path)
    try:
        with patch.object(project,'items_iter',side_effect=AssertionError('per-request whole-graph scan')):
            scope.validate_canonical(project,check_items=False)
    finally:store.close()


def test_role_progress_excludes_locks_and_keeps_translate_and_polish_denominators_distinct(tmp_path):
    from test_game_task_reset import seed
    store,_,host=seed(tmp_path)
    try:
        assert game_task_progress(host.project,'translate')=={'pending':2,'completed':2,'total':4}
        assert game_task_progress(host.project,'polish')=={'pending':1,'completed':1,'total':2}
    finally:store.close()
