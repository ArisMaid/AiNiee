"""Malformed UI status must not bypass a canonical scheduling readback."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ModuleFolders.Domain.GameProject.Models import TranslationUnit,TranslationProposal,Occurrence,hash_text
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.CacheBridge import build_projection,sync_generated_cache
from ModuleFolders.Service.Cache.CacheManager import CacheManager
from ModuleFolders.Service.Cache.CacheItem import TranslationStatus
from ModuleFolders.Service.GameProject.GameTaskScope import coordinator_for

@pytest.mark.parametrize('status',[None,True,'2'])
def test_malformed_table_notice_must_not_downgrade_a_polished_cache(tmp_path,status):
    from UserInterface.EditView.Proofreading.Table.BasicTablePage import BasicTablePage
    with ProjectStore.create(tmp_path/'project',{'project_id':'notice-type','engine':'rpgmaker-mz',
            'source_root':str(tmp_path/'source')}) as store:
        unit=TranslationUnit('u','menu','原文',occurrences=(Occurrence('o','data/System.json',{'pointer':'/gameTitle'},hash_text('原文')),))
        store.replace_units([unit]);store.commit(TranslationProposal('u','接受文本',unit.source_hash,origin='polish'))
        manager=object.__new__(CacheManager);manager.project=build_projection(store)
        item=next(manager.project.items_iter())
        coordinator=coordinator_for(manager);scope=coordinator.reserve(manager.project,'table-polish')
        coordinator.accept(manager.project,scope.payload())
        page=SimpleNamespace(file_path='data/System.json',COL_TRANS=2,COL_NUM=0,cache_manager=manager,
            _game_table_project=manager.project,
            _items_by_text_index={0:item},table=SimpleNamespace(rowCount=lambda:0,scheduleResizeRowsToContents=Mock()))
        page._sync_local_item=Mock(side_effect=lambda *args:BasicTablePage._sync_local_item(page,*args))
        BasicTablePage._on_table_update(page,0,{**scope.payload(),'file_path':'data/System.json','target_column_index':2,
            'translation_status':status,'updated_items':{0:'接受文本'}})
        assert item.translation_status==TranslationStatus.POLISHED
        page._sync_local_item.assert_not_called()
        # The lower-level no-status readback remains a separate supported API.
        assert sync_generated_cache(manager,'data/System.json',0,'接受文本') is True
        assert item.translation_status==TranslationStatus.POLISHED
