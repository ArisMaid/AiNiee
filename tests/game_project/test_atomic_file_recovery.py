"""Protected Windows atomic writes: recover sharing errors, retain failures."""
import ctypes
from ctypes import wintypes
import os
import threading
import time
import pytest
from ModuleFolders.Service.GameProject import PathGuard


def locked(path):
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
        wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    api.CreateFileW.restype=wintypes.HANDLE
    api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle.restype=wintypes.BOOL
    handle=api.CreateFileW(str(path),0x80000000,3,None,3,0x80,None)
    assert handle!=ctypes.c_void_p(-1).value,ctypes.get_last_error()
    return api,handle


@pytest.mark.skipif(os.name!='nt',reason='Real Windows delete-sharing handle')
def test_atomic_overwrite_recovers_native_short_lock(tmp_path,monkeypatch):
    path=tmp_path/'中文 空格/Map001.json';path.parent.mkdir();path.write_bytes(b'original')
    api,handle=locked(path);first_error=threading.Event();released=threading.Event();observed=[]
    original_replace=os.replace
    def replace(source,target):
        try:return original_replace(source,target)
        except OSError:
            first_error.set();raise
    monkeypatch.setattr(os,'replace',replace)
    def release():
        if first_error.wait(5):
            observed.append(path.read_bytes());time.sleep(.08)
        api.CloseHandle(handle);released.set()
    thread=threading.Thread(target=release);thread.start()
    try:PathGuard.atomic_write(path,b'new Chinese bytes',overwrite=True)
    finally:
        thread.join(6)
        assert released.is_set()
    assert first_error.is_set() and observed==[b'original']
    assert path.read_bytes()==b'new Chinese bytes'
    assert not list(path.parent.glob('.*.staging'))


@pytest.mark.skipif(os.name!='nt',reason='Real Windows delete-sharing handle')
def test_atomic_persistent_lock_retains_original_and_one_unique_staging(tmp_path,monkeypatch):
    path=tmp_path/'Map001.json';path.write_bytes(b'original')
    older=tmp_path/'.Map001.json.older.staging';older.write_bytes(b'prior failed write')
    api,handle=locked(path);delays=[];errors=[];original_replace=os.replace
    def replace(source,target):
        try:return original_replace(source,target)
        except OSError as error:errors.append(error.winerror);raise
    monkeypatch.setattr(os,'replace',replace);monkeypatch.setattr(time,'sleep',delays.append)
    try:
        with pytest.raises(PermissionError):PathGuard.atomic_write(path,b'new bytes',overwrite=True)
    finally:api.CloseHandle(handle)
    assert len(errors)==6 and set(errors)<={5,32,33}
    assert delays==[.03,.06,.12,.24,.48] and path.read_bytes()==b'original'
    staged=[p for p in tmp_path.glob('.*.staging') if p!=older]
    assert len(staged)==1 and staged[0].read_bytes()==b'new bytes'
    assert older.read_bytes()==b'prior failed write'


@pytest.mark.parametrize('winerror',[None,112])
def test_atomic_unrelated_failure_is_immediate_and_keeps_both_inputs(tmp_path,monkeypatch,winerror):
    path=tmp_path/'data.json';path.write_bytes(b'original');calls=[]
    def fail(*args):
        calls.append(args);error=OSError('unrelated I/O failure')
        if winerror is not None:error.winerror=winerror
        raise error
    monkeypatch.setattr(os,'replace',fail)
    monkeypatch.setattr(time,'sleep',lambda _:pytest.fail('must not retry unrelated error'))
    with pytest.raises(OSError,match='unrelated'):PathGuard.atomic_write(path,b'new',overwrite=True)
    assert len(calls)==1 and path.read_bytes()==b'original'
    assert [p.read_bytes() for p in tmp_path.glob('.*.staging')]==[b'new']


def test_atomic_no_overwrite_still_refuses_existing_target_without_retries(tmp_path,monkeypatch):
    path=tmp_path/'data.json';path.write_bytes(b'original')
    monkeypatch.setattr(os,'replace',lambda *_:pytest.fail('no-overwrite used replace'))
    monkeypatch.setattr(time,'sleep',lambda _:pytest.fail('no-overwrite must not retry'))
    with pytest.raises(FileExistsError):PathGuard.atomic_write(path,b'new')
    assert path.read_bytes()==b'original' and not list(tmp_path.glob('.*.staging'))


@pytest.mark.skipif(os.name!='nt',reason='Real Windows handle and hardlink guards')
@pytest.mark.parametrize('link_kind',['target','staging'])
def test_atomic_retry_rechecks_paths_and_refuses_new_hardlink(tmp_path,monkeypatch,link_kind):
    path=tmp_path/'Map001.json';path.write_bytes(b'original')
    api,handle=locked(path);released=False;delays=[]
    def change_boundary(delay):
        nonlocal released
        delays.append(delay);api.CloseHandle(handle);released=True
        candidate=path if link_kind=='target' else next(tmp_path.glob('.*.staging'))
        os.link(candidate,tmp_path/'retained-alias')
    monkeypatch.setattr(time,'sleep',change_boundary)
    try:
        with pytest.raises(PathGuard.PathViolation,match='hard'):
            PathGuard.atomic_write(path,b'new bytes',overwrite=True)
    finally:
        if not released:api.CloseHandle(handle)
    assert delays==[.03] and path.read_bytes()==b'original'
    assert [p.read_bytes() for p in tmp_path.glob('.*.staging')]==[b'new bytes']
