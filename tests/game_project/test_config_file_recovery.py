"""Real Windows delete-sharing handles, persistent failures and retained staging."""
import ctypes
from ctypes import wintypes
import os
import threading
import pytest
from ModuleFolders.Infrastructure.Platform import ConfigFile


def lock_without_delete_sharing(path):
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
        wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    api.CreateFileW.restype=wintypes.HANDLE
    api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle.restype=wintypes.BOOL
    handle=api.CreateFileW(str(path),0x80000000,3,None,3,0x80,None)
    assert handle!=ctypes.c_void_p(-1).value,ctypes.get_last_error()
    return api,handle


@pytest.mark.skipif(os.name!='nt',reason='Windows native sharing semantics')
def test_live_shared_read_handle_recovers_after_release_and_keeps_old_file_until_then(tmp_path):
    path=tmp_path/'中文 空格/config.json';path.parent.mkdir();path.write_text('{"old":1}',encoding='utf-8')
    api,handle=lock_without_delete_sharing(path);closed=threading.Event();observed=[]
    def release():
        observed.append(path.read_text(encoding='utf-8'))
        api.CloseHandle(handle);closed.set()
    timer=threading.Timer(.15,release);timer.start()
    try:ConfigFile.write_config_text(path,'{"new":"中文"}')
    finally:
        timer.join()
        if not closed.is_set():api.CloseHandle(handle)
    assert observed==['{"old":1}']
    assert path.read_text(encoding='utf-8')=='{"new":"中文"}' and not list(path.parent.glob('*.tmp'))


@pytest.mark.skipif(os.name!='nt',reason='Windows native sharing semantics')
def test_persistent_lock_is_bounded_and_retains_unique_new_file(tmp_path,monkeypatch):
    path=tmp_path/'config.json';path.write_text('{"old":1}',encoding='utf-8')
    legacy=tmp_path/'config.json.tmp';legacy.write_text('previous failure retained',encoding='utf-8')
    api,handle=lock_without_delete_sharing(path);delays=[]
    monkeypatch.setattr(ConfigFile.time,'sleep',delays.append)
    try:
        with pytest.raises(PermissionError):ConfigFile.write_config_text(path,'{"new":2}')
    finally:api.CloseHandle(handle)
    assert delays==list(ConfigFile._DELAYS) and path.read_text(encoding='utf-8')=='{"old":1}'
    staged=[p for p in tmp_path.glob('config.json.*.tmp')]
    assert len(staged)==1 and staged[0].read_text(encoding='utf-8')=='{"new":2}'
    assert legacy.read_text(encoding='utf-8')=='previous failure retained'


def test_other_os_errors_are_not_retried_and_previous_config_survives(tmp_path,monkeypatch):
    path=tmp_path/'config.json';path.write_text('original',encoding='utf-8');calls=[]
    def fail(*args):calls.append(args);raise OSError('unrelated failure')
    monkeypatch.setattr(ConfigFile.os,'replace',fail)
    monkeypatch.setattr(ConfigFile.time,'sleep',lambda _:pytest.fail('unrelated failure retried'))
    with pytest.raises(OSError,match='unrelated'):ConfigFile.write_config_text(path,'new')
    assert len(calls)==1 and path.read_text(encoding='utf-8')=='original'
    assert len(list(tmp_path.glob('*.tmp')))==1


@pytest.mark.parametrize('operation',['load','save'])
def test_config_read_io_failure_never_becomes_an_empty_overwrite(tmp_path,monkeypatch,operation):
    import builtins
    from ModuleFolders.Config import Config
    path=tmp_path/'config.json';original=b'{"existing_setting": 42}';path.write_bytes(original)
    actual_open=builtins.open
    def unreadable(file,*args,**kwargs):
        if str(file)==str(path):raise PermissionError('synthetic read failure')
        return actual_open(file,*args,**kwargs)
    with monkeypatch.context() as guard:
        guard.setattr(Config,'config_path',lambda:str(path))
        guard.setattr(Config,'migrate_config_if_needed',lambda:False)
        guard.setattr(builtins,'open',unreadable)
        with pytest.raises(PermissionError,match='synthetic read failure'):
            if operation=='load':Config.ConfigMixin().load_config()
            else:Config.ConfigMixin().save_config({'new_setting':1})
    assert path.read_bytes()==original and not (tmp_path/'config.json.corrupt').exists()
    assert not list(tmp_path.glob('*.tmp'))
