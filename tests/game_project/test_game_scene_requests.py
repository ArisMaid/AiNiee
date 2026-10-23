"""Codex-owned end-to-end table request boundaries using a local requester stub."""
import json
from types import SimpleNamespace
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Domain.GameProject.Models import Occurrence,TranslationUnit,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.CacheBridge import build_projection
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner


def project(tmp_path,scenes):
    store=ProjectStore.create(tmp_path/'project',{'project_id':'scene-request',
        'engine':'rpgmaker-mz','source_root':str(tmp_path/'source')})
    units=[TranslationUnit(f'u{i}','dialogue',f'台词{i}',scene_id=scene,
        occurrences=(Occurrence(f'o{i}','data/Map001.json',{'pointer':f'/events/{i}/name'},hash_text(f'台词{i}')),))
        for i,scene in enumerate(scenes)]
    store.replace_units(units)
    return store,SimpleNamespace(project=build_projection(store))


def config():
    return SimpleNamespace(request_timeout=2,project_terms_data=[],get_active_platform_configuration=lambda:{})


class Requester:
    def __init__(self):self.requests=[]
    def sent_request(self,messages,*_):
        payload=json.loads(messages[-1]['content']);self.requests.append(list(payload))
        return False,'',json.dumps({key:'译文'+key for key in payload}),1,1


def table(manager,selected,requester):
    from ModuleFolders.Service.SimpleExecutor.SimpleExecutor import SimpleExecutor
    executor=SimpleExecutor(cache_manager=manager)
    try:
        return executor._process_game_table({'file_path':'data/Map001.json',
            'items_to_translate':[{'text_index':index} for index in selected]},
            'translate',config=config(),requester=requester)
    finally:executor._cleanup_event_subscriptions()


def test_table_requests_use_original_file_scene_order(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,manager=project(tmp_path,['a','a','b'])
    try:
        requester=Requester();result=table(manager,[2,1,0],requester)
        assert result=={'row_count':3,'error':''}
        assert requester.requests==[['u0','u1'],['u2']]
        assert all(store.translation(f'u{i}')['text']=='译文u'+str(i) for i in range(3))
    finally:store.close()


def test_unselected_other_scene_still_separates_table_requests(tmp_path,monkeypatch):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,manager=project(tmp_path,['a','b','a'])
    try:
        requester=Requester();result=table(manager,[0,2],requester)
        assert result=={'row_count':2,'error':''}
        assert requester.requests==[['u0'],['u2']]
        assert store.translation('u1') is None
    finally:store.close()


def test_forged_projection_scene_cannot_bypass_canonical_request_boundary(tmp_path):
    store,manager=project(tmp_path,['a','b'])
    try:
        items=list(manager.project.items_iter())
        for item in items:item.set_extra('scene_id','forged-same-scene')
        with pytest.raises(ValueError,match='MIXED_GAME_SCENE_BATCH'):
            GameBatchRunner(items,config())
        assert store.jobs()==[]
        assert all(store.translation(f'u{i}') is None for i in range(2))
    finally:store.close()


def test_mixed_known_and_empty_scenes_remain_sendable_as_separate_batches(tmp_path,monkeypatch):
    from ModuleFolders.Service.Cache.CacheManager import CacheManager
    from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,manager=project(tmp_path,['a','','b'])
    try:
        host=object.__new__(CacheManager);host.project=manager.project
        chunks,_,_=host.generate_item_chunks('line',99,2,TaskType.TRANSLATION)
        requester=Requester()
        for chunk in chunks:assert GameBatchRunner(chunk,config()).run(requester)['check_result']
        assert requester.requests==[['u0'],['u1'],['u2']]
    finally:store.close()


@pytest.mark.parametrize('index',[-1,'0',False])
def test_invalid_table_selection_makes_no_requests_or_commits(tmp_path,monkeypatch,index):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,manager=project(tmp_path,['a','a'])
    try:
        requester=Requester();result=table(manager,[index],requester)
        assert result['row_count']==0 and result['error']
        assert requester.requests==[] and store.jobs()==[]
        assert all(store.translation(f'u{i}') is None for i in range(2))
    finally:store.close()
