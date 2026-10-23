"""No cache temp cleanup and no repeat projection/IO on accepted GUI handover."""
from pathlib import Path
import threading
from unittest.mock import patch
import pytest
from ModuleFolders.Service.Cache.CacheManager import CacheManager
from ModuleFolders.Service.Cache.CacheProject import CacheProject,CacheProjectStatistics


def project(tmp_path,kind='RpgGame',root=True):
    return CacheProject(project_id='prepared-cache',project_type=kind,project_name='合成项目',stats_data=CacheProjectStatistics(),
        extra={'game_project_root':str(tmp_path/'project')} if root else {})


def test_cache_replace_failure_keeps_old_data_and_unique_failed_stage(tmp_path,monkeypatch):
    cache=tmp_path/'cache';cache.mkdir();old=cache/CacheManager.CACHE_FILENAME;old.write_text('old cache',encoding='utf-8')
    stats=cache/CacheManager.STATS_FILENAME;stats.write_text('old stats',encoding='utf-8')
    prior=cache/'older.tmp';prior.write_text('prior failure',encoding='utf-8')
    monkeypatch.setattr(CacheManager,'get_project_cache_dir',classmethod(lambda cls,key:str(cache)))
    def fail(*_):raise PermissionError('injected cache replacement failure')
    monkeypatch.setattr('os.replace',fail)
    # Prevent the old implementation from deleting even its own failing tmp.
    monkeypatch.setattr('os.remove',lambda *_:(_ for _ in ()).throw(AssertionError('deletion blocked')))
    with pytest.raises(PermissionError,match='cache replacement'):
        CacheManager._write_project_cache_files(project(tmp_path))
    assert old.read_text(encoding='utf-8')=='old cache' and stats.read_text(encoding='utf-8')=='old stats'
    staged=[p for p in cache.glob('*.tmp') if p!=prior]
    assert len(staged)==1 and b'prepared-cache' in staged[0].read_bytes()
    assert prior.read_text(encoding='utf-8')=='prior failure'


def test_cache_success_keeps_formats_and_older_failed_temporary(tmp_path,monkeypatch):
    import msgspec
    import json
    cache=tmp_path/'cache';cache.mkdir();prior=cache/'old.tmp';prior.write_bytes(b'retained')
    monkeypatch.setattr(CacheManager,'get_project_cache_dir',classmethod(lambda cls,key:str(cache)))
    current=project(tmp_path);CacheManager._write_project_cache_files(current)
    parsed=msgspec.json.decode((cache/CacheManager.CACHE_FILENAME).read_bytes(),type=CacheProject)
    assert parsed.project_id==current.project_id and parsed.project_name==current.project_name
    assert isinstance(json.loads((cache/CacheManager.STATS_FILENAME).read_text(encoding='utf-8')),dict)
    assert list(cache.glob('*.tmp'))==[prior] and prior.read_bytes()==b'retained'


def test_prepared_adoption_does_not_rebuild_projection_or_change_the_normal_load_contract(tmp_path):
    manager=CacheManager.__new__(CacheManager);manager.file_lock=threading.Lock();manager.project=None
    prepared=project(tmp_path)
    with patch('ModuleFolders.Service.GameProject.CacheBridge.refresh_projection',side_effect=AssertionError('GUI performed IO')):
        manager._adopt_prepared_game_projection(prepared)
    assert manager.project is prepared and prepared.project_create_time
    replacement=project(tmp_path)
    with patch('ModuleFolders.Service.GameProject.CacheBridge.refresh_projection',return_value=replacement) as refresh:
        manager.load_from_project(prepared)
    refresh.assert_called_once_with(prepared);assert manager.project is replacement


@pytest.mark.parametrize('bad_kind,bad_root',[('Text',True),('RpgGame',False)])
def test_prepared_adoption_refuses_other_or_unbound_projects_without_mutation(tmp_path,bad_kind,bad_root):
    manager=CacheManager.__new__(CacheManager);manager.file_lock=threading.Lock();sentinel=object();manager.project=sentinel
    with pytest.raises(ValueError):manager._adopt_prepared_game_projection(project(tmp_path,bad_kind,bad_root))
    assert manager.project is sentinel
