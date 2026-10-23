"""Release checks for the new installation boundary, using tiny synthetic archives."""
import hashlib
import json
import threading
import zipfile
from unittest.mock import patch

import pytest
from ModuleFolders.Service.GameProject.ExternalTools import ExternalTools, ToolError, Cancelled, _member


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv('AINIEE_EXTERNAL_TOOLS_HOME',str(tmp_path/'tools'))
    monkeypatch.setenv('AINIEE_EXTERNAL_TOOLS_CONFIG',str(tmp_path/'settings.json'))
    return ExternalTools()


def test_select_checks_version_and_keeps_previous_configuration(manager,tmp_path):
    root=tmp_path/'existing';root.mkdir()
    (root/'Translator++.exe').write_bytes(b'not executed')
    (root/'package.json').write_text('{"version":"8.8.9"}')
    assert manager.select('translatorpp',root)['ready']
    before=manager.config.read_bytes()
    (root/'package.json').write_text('{"version":"9.0"}')
    with pytest.raises(ToolError,match='8.8.9'):manager.select('translatorpp',root)
    assert manager.config.read_bytes()==before
    assert not manager.status('translatorpp')['ready']


def test_wrong_hash_is_not_used_or_executed(manager):
    spec=manager.catalog['tools']['rpgmtl']
    cache=manager.home/'下载缓存/7.2.4.1';cache.mkdir(parents=True)
    (cache/'rpgmtl.zip').write_bytes(b'wrong content')
    with patch('urllib.request.urlopen',side_effect=OSError('offline')):
        with pytest.raises(ToolError,match='下载失败'):manager.install('rpgmtl')
    assert not manager.config.exists()


def test_cancel_before_download_does_not_register(manager):
    cancel=threading.Event();cancel.set()
    with pytest.raises(Cancelled):manager.install('rpgmtl',cancel=cancel)
    assert not manager.config.exists()


@pytest.mark.parametrize('name',['../escape','/absolute','C:/escape','folder/../../escape','a\\..\\escape'])
def test_reject_archive_paths(name):
    with pytest.raises(ToolError):_member(name)


def test_zip_install_and_reuse_register_actual_root(manager,tmp_path):
    package=tmp_path/'fixture.zip'
    text=b'fixture'
    with zipfile.ZipFile(package,'w') as archive:archive.writestr('fixture/plugins/json.py',text)
    manager.catalog['tools']['rpgmtl'].update(archive_prefix='fixture/',
        required=['plugins/json.py'],entry_sha256={'plugins/json.py':hashlib.sha256(text).hexdigest()})
    with patch.object(manager,'_download',return_value=package):
        result=manager.install('rpgmtl')
        assert result['ready'] and (manager.path('rpgmtl')/'plugins/json.py').read_bytes()==text
        assert manager.install('rpgmtl')['path']==result['path']
    assert json.loads(manager.config.read_text())['rpgmtl']==result['path']


def test_hostile_zip_preserves_existing_files(manager,tmp_path):
    package=tmp_path/'bad.zip';outside=manager.home/'keep.txt'
    manager.home.mkdir();outside.write_bytes(b'keep')
    with zipfile.ZipFile(package,'w') as archive:archive.writestr('../keep.txt',b'changed')
    with patch.object(manager,'_download',return_value=package):
        with pytest.raises(ToolError,match='不安全路径'):manager.install('rpgmtl')
    assert outside.read_bytes()==b'keep' and not manager.config.exists()
