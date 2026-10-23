"""Independent follow-up guards beyond the worker's initial acceptance file."""
import json
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner
from test_game_batch_preparation import create,config,preparation,references,Requester


def test_policy_change_during_request_keeps_raw_response_without_accepting(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,items=create(tmp_path)
    class ChangePolicy(Requester):
        def sent_request(self,*args):
            result=super().sent_request(*args)
            store.update_metadata({'target_language':'en'})
            return result
    try:
        batch=GameBatchRunner([items[2]],config(),preparation=preparation(store.root))
        requester=ChangePolicy()
        with pytest.raises(ValueError,match='REVISION_CONFLICT'):batch.run(requester)
        assert len(requester.calls)==1
        assert store.translation('u2') is None
        job=store.jobs()[-1]
        assert job['run_state']=='FAILED' and 'u2' in json.loads(job['result']['response_text'])
    finally:store.close()


@pytest.mark.parametrize('relative',[0,1])
def test_previous_input_must_actually_precede_requested_units(tmp_path,relative):
    store,_,items=create(tmp_path)
    try:
        with pytest.raises(ValueError,match='CONTEXT'):
            GameBatchRunner([items[2]],config(),previous_items=[items[2+relative]])
        assert store.jobs()==[]
    finally:store.close()


def test_duplicate_requested_id_is_rejected_before_payload_collapse(tmp_path):
    store,_,items=create(tmp_path)
    try:
        with pytest.raises(ValueError,match='DUPLICATE|CONTEXT'):
            GameBatchRunner([items[2],items[2]],config())
        assert store.jobs()==[]
    finally:store.close()


def test_current_manual_lock_skips_target_without_invalidating_source_snapshot(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,_,items=create(tmp_path)
    try:
        shared=preparation(store.root)
        store.set_locked('u2',True)
        batch=GameBatchRunner([items[2]],config(),preparation=shared)
        requester=Requester()
        assert batch.run(requester)['check_result'] and requester.calls==[]
        assert store.jobs()==[] and store.translation('u2')['manual_locked']
    finally:store.close()


def test_table_stop_before_preparation_makes_no_graph_or_model_request(tmp_path,monkeypatch):
    from test_game_scene_requests import table
    from types import SimpleNamespace
    from unittest.mock import patch
    from ModuleFolders.Service.GameProject.CacheBridge import build_projection
    store,_,_=create(tmp_path)
    manager=SimpleNamespace(project=build_projection(store)); requester=Requester()
    monkeypatch.setattr(Base,'work_status',Base.STATUS.STOPING)
    try:
        with patch('ModuleFolders.Service.GameProject.GameBatchPreparation.GameBatchPreparation',
                   side_effect=AssertionError('cancelled operation loaded graph')):
            result=table(manager,[1],requester)
        assert result=={'row_count':0,'error':'GAME_TABLE_CANCELLED'}
        assert requester.calls==[] and store.jobs()==[]
    finally:store.close()
