"""Codex-owned scene regression: no model calls or private game input."""
from unittest.mock import patch
from ModuleFolders.Infrastructure.TaskConfig.TaskType import TaskType
from ModuleFolders.Service.Cache.CacheManager import CacheManager
from ModuleFolders.Service.Cache.CacheItem import CacheItem, TranslationStatus
from ModuleFolders.Service.Cache.CacheFile import CacheFile
from ModuleFolders.Service.Cache.CacheProject import CacheProject


def manager(scenes, *, game=True, statuses=None):
    project=CacheProject(project_type='RpgGame' if game else 'Txt',
        extra={'game_project_root':'synthetic-unused-root'} if game else {})
    file=CacheFile(storage_path='data/Map001.json')
    for index,scene in enumerate(scenes):
        file.add_item(CacheItem(text_index=index, source_text=f'行{index}',
            translated_text=f'译{index}',
            translation_status=(statuses[index] if statuses else TranslationStatus.UNTRANSLATED),
            extra={'scene_id':scene,'unit_id':f'u{index}'}))
    project.add_file(file)
    host=object.__new__(CacheManager)
    host.project=project
    return host


def indexes(chunks):
    return [[item.text_index for item in chunk] for chunk in chunks]


def test_translation_keeps_distinct_events_in_distinct_batches():
    host=manager(['map1:event1:page0','map1:event1:page0','map1:event2:page0'])
    chunks,previous,paths=host.generate_item_chunks('line',99,2,TaskType.TRANSLATION)
    assert indexes(chunks)==[[0,1],[2]]
    assert indexes(previous)==[[],[]]
    assert paths==['data/Map001.json','data/Map001.json']


def test_previous_lines_do_not_cross_scene_boundary():
    host=manager(['a','a','b','b'])
    chunks,previous,_=host.generate_item_chunks('line',1,3,TaskType.TRANSLATION)
    assert indexes(chunks)==[[0],[1],[2],[3]]
    assert indexes(previous)==[[],[0],[],[2]]


def test_polish_keeps_scene_and_filtered_item_identity():
    host=manager(['a','a','b','b'],statuses=[TranslationStatus.TRANSLATED,
        TranslationStatus.EXCLUDED,TranslationStatus.TRANSLATED,TranslationStatus.TRANSLATED])
    chunks,previous,_=host.generate_item_chunks('line',99,2,TaskType.POLISH)
    assert indexes(chunks)==[[0],[2,3]]
    assert indexes(previous)==[[],[]]


def test_token_budget_and_scene_change_both_split():
    host=manager(['a','a','a','b','b'])
    with patch.object(CacheItem,'get_token_count',return_value=3):
        chunks,previous,_=host.generate_item_chunks('token',6,2,TaskType.TRANSLATION)
    assert indexes(chunks)==[[0,1],[2],[3,4]]
    assert indexes(previous)==[[],[0,1],[]]


def test_noncontiguous_scene_does_not_pull_context_across_other_events():
    host=manager(['a','b','a'])
    chunks,previous,_=host.generate_item_chunks('line',99,3,TaskType.TRANSLATION)
    assert indexes(chunks)==[[0],[1],[2]]
    assert indexes(previous)==[[],[],[]]


def test_filtered_other_scene_still_breaks_context_continuity():
    host=manager(['a','b','a'],statuses=[TranslationStatus.UNTRANSLATED,
        TranslationStatus.EXCLUDED,TranslationStatus.UNTRANSLATED])
    chunks,previous,_=host.generate_item_chunks('line',99,3,TaskType.TRANSLATION)
    assert indexes(chunks)==[[0],[2]]
    assert indexes(previous)==[[],[]]


def test_ordinary_document_chunking_retains_previous_behavior():
    host=manager(['a','b','c'],game=False)
    chunks,previous,_=host.generate_item_chunks('line',2,2,TaskType.TRANSLATION)
    assert indexes(chunks)==[[0,1],[2]]
    assert indexes(previous)==[[],[0,1]]


def test_all_missing_scene_ids_keep_within_file_batching():
    host=manager(['','',''])
    chunks,previous,_=host.generate_item_chunks('line',99,2,TaskType.TRANSLATION)
    assert indexes(chunks)==[[0,1,2]]
    assert indexes(previous)==[[]]
