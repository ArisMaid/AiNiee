"""Successful game polish must survive projection rebuild and end the round."""
from dataclasses import replace
import json
from types import SimpleNamespace
import pytest
from ModuleFolders.Base.Base import Base
from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Service.GameProject.CacheBridge import build_projection,update_cached_item
from ModuleFolders.Service.GameProject.GameBatchRunner import GameBatchRunner
from ModuleFolders.Service.Cache.CacheManager import CacheManager
from ModuleFolders.Service.Cache.CacheItem import TranslationStatus
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
from test_game_batch_preparation import create,config


def item_for(project,unit_id):
    return next(item for item in project.items_iter() if item.get_extra('unit_id')==unit_id)


@pytest.mark.parametrize('reply',['校润后文本','校润前文本'])
def test_successful_polish_is_persistently_excluded_from_next_polish_round(tmp_path,monkeypatch,reply):
    monkeypatch.setattr(Base,'work_status',Base.STATUS.TASKING)
    store,units,_=create(tmp_path)
    class Local:
        def sent_request(self,messages,*_):
            targets=json.loads(messages[-1]['content'])
            assert set(targets)=={'u2'}
            return False,'',json.dumps({'u2':reply},ensure_ascii=False),1,1
    try:
        store.commit(TranslationProposal('u2','校润前文本',units[2].source_hash,0,origin='manual'))
        project=build_projection(store); item=item_for(project,'u2')
        assert item.translation_status==TranslationStatus.TRANSLATED
        assert GameBatchRunner([item],config(),mode='polish').run(Local())['check_result']
        assert item.translated_text==reply and item.translation_status==TranslationStatus.POLISHED
        fresh=build_projection(store)
        assert item_for(fresh,'u2').translation_status==TranslationStatus.POLISHED
        host=object.__new__(CacheManager);host.project=fresh
        chunks,_,_=host.generate_item_chunks('line',20,10,TaskType.POLISH)
        assert chunks==[]
        assert store.translation('u2')['origin']=='polish'
    finally:store.close()


@pytest.mark.parametrize('change',['manual_edit','stale_source','manual_lock'])
def test_polish_state_yields_to_fresh_edit_stale_source_and_lock(tmp_path,change):
    store,units,_=create(tmp_path)
    try:
        store.commit(TranslationProposal('u2','已校润文本',units[2].source_hash,0,origin='polish'))
        before=build_projection(store);item=item_for(before,'u2')
        assert item.translation_status==TranslationStatus.POLISHED
        expected=TranslationStatus.TRANSLATED
        if change=='manual_edit':
            store.commit(TranslationProposal('u2','人工修订',units[2].source_hash,1,origin='manual'))
        elif change=='stale_source':
            store.replace_units([*units[:2],replace(units[2],source_text='新的来源',source_hash=''),*units[3:]])
            expected=TranslationStatus.UNTRANSLATED
        else:
            store.set_locked('u2',True);expected=TranslationStatus.EXCLUDED
        update_cached_item(item,store)
        assert item.translation_status==expected
        assert item_for(build_projection(store),'u2').translation_status==expected
    finally:store.close()
