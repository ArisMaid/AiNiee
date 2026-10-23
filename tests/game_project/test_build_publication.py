"""Actual Windows directory-sharing and no-clobber publication boundaries."""
from contextlib import contextmanager
from pathlib import Path
import ctypes,os,threading,uuid
from ctypes import wintypes
import pytest
from ModuleFolders.Service.GameProject.BuildPublication import publish_staging

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows sharing semantics')

def paths(tmp_path):
    identity=uuid.uuid4().hex
    staging=tmp_path/('.staging-'+identity);staging.mkdir()
    (staging/'payload.txt').write_bytes(b'PRESERVE')
    final=tmp_path/('game-zh-CN-'+identity)
    assert staging.absolute().parent==final.absolute().parent==tmp_path.absolute()
    return staging,final

@contextmanager
def deny_delete_share(path):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0x02000000,None)
    assert handle not in (None,ctypes.c_void_p(-1).value),ctypes.get_last_error()
    closed=threading.Event();lock=threading.Lock()
    def close():
        with lock:
            if not closed.is_set():
                assert kernel.CloseHandle(handle)
                closed.set()
    try:yield close
    finally:close()

def test_real_directory_handle_short_occupation_retries_and_publishes(tmp_path):
    staging,final=paths(tmp_path)
    with deny_delete_share(staging) as close:
        with pytest.raises(PermissionError):staging.rename(final)
        timer=threading.Timer(.08,close);timer.start()
        try:publish_staging(staging,final)
        finally:timer.join(timeout=2)
    assert not staging.exists() and (final/'payload.txt').read_bytes()==b'PRESERVE'

def test_persistent_directory_handle_failure_retains_complete_staging(tmp_path):
    staging,final=paths(tmp_path)
    with deny_delete_share(staging):
        with pytest.raises(PermissionError):publish_staging(staging,final)
    assert not final.exists() and (staging/'payload.txt').read_bytes()==b'PRESERVE'

def test_existing_output_is_never_overwritten(tmp_path):
    staging,final=paths(tmp_path);final.mkdir();(final/'original.txt').write_bytes(b'ORIGINAL')
    with pytest.raises(FileExistsError):publish_staging(staging,final)
    assert (final/'original.txt').read_bytes()==b'ORIGINAL'
    assert (staging/'payload.txt').read_bytes()==b'PRESERVE'
