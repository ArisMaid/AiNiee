"""Native startup/ownership checks; all children belong to these fixtures."""
from contextlib import closing
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

import pytest

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows native ownership contract')
from ModuleFolders.Infrastructure.Platform.WindowsJob import WindowsJob

ROOT=Path(__file__).resolve().parents[2]
PYTHON=str(Path(sys._base_executable).resolve())


def native():
    from ModuleFolders.Infrastructure.Platform.WindowsProcess import WindowsProcess
    return WindowsProcess


def environment():
    return {k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP'}}


def folder():
    parent=ROOT/'work/acceptance';parent.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='native-process-',dir=parent));target=root/'中文 空格'
    target.mkdir();return target


def kernel():
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
    api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];api.WaitForSingleObject.restype=wintypes.DWORD
    api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle.restype=wintypes.BOOL
    api.GetCurrentProcess.restype=wintypes.HANDLE
    api.GetProcessHandleCount.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    api.GetProcessHandleCount.restype=wintypes.BOOL
    return api


def watch(pid):
    api=kernel();handle=api.OpenProcess(0x100000|0x1000,False,pid)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    return handle


def handle_count():
    api=kernel();count=wintypes.DWORD()
    assert api.GetProcessHandleCount(api.GetCurrentProcess(),ctypes.byref(count));return count.value


def line(process):
    messages=queue.Queue();reader=threading.Thread(target=lambda:messages.put(process.stdout.readline()),daemon=True)
    reader.start();data=messages.get(timeout=10);reader.join(1);assert data
    return json.loads(data)


def test_unicode_arguments_env_and_binary_pipes_are_preserved():
    cwd=folder();extra=['', '空 格', 'a"b', 'trailing\\', '$(not a shell)']
    env=dict(environment(),NATIVE_TEST_VALUE='中文 值')
    code="import os,sys,json;print(json.dumps([sys.argv[1:],os.getcwd(),os.environ.get('NATIVE_TEST_VALUE'),dict(os.environ)]),flush=True);sys.stdout.buffer.write(sys.stdin.buffer.read());sys.stderr.buffer.write(b'err')"
    with WindowsJob() as job,native()([PYTHON,'-u','-c',code,*extra],cwd=cwd,env=env,job=job) as process:
        process.stdin.write(b'\x00\xffpayload');process.stdin.close()
        actual=json.loads(process.stdout.readline())
        assert actual[0]==extra and Path(actual[1])==cwd and actual[2]=='中文 值'
        assert not any('KEY' in k or k.upper() in {'NODE_OPTIONS','PYTHONPATH'} for k in actual[3])
        assert process.stdout.read()==b'\x00\xffpayload' and process.stderr.read()==b'err'
        assert process.wait(10)==0 and process.poll()==0


def test_child_is_suspended_until_hook_returns_and_hook_failure_cleans_handles():
    cwd=folder();marker=cwd/'executed.txt';seen=[]
    def observe(process):
        assert not marker.exists();seen.append(process.pid)
    code='from pathlib import Path;Path('+repr(str(marker))+').write_text("ran")'
    with WindowsJob() as job,native()([PYTHON,'-c',code],cwd=cwd,env=environment(),job=job,on_suspended=observe) as process:
        assert seen==[process.pid] and process.wait(10)==0
    assert marker.read_text()=='ran'
    baseline=handle_count();handles=[]
    def fail(process):
        handles.append(watch(process.pid));raise RuntimeError('injected before resume')
    try:
        for _ in range(3):
            with WindowsJob() as job,pytest.raises(RuntimeError,match='injected before resume'):
                native()([PYTHON,'-c','import time;time.sleep(300)'],cwd=cwd,env=environment(),job=job,on_suspended=fail)
        assert all(kernel().WaitForSingleObject(handle,5000)==0 for handle in handles)
    finally:
        for handle in handles:assert kernel().CloseHandle(handle)
    assert handle_count()==baseline


def test_close_terminates_live_descendant_even_after_primary_exits():
    cwd=folder();code="import subprocess,sys,json;child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);print(json.dumps({'pid':child.pid}),flush=True)"
    with subprocess.Popen([PYTHON,'-c','import time;time.sleep(300)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as sentinel:
        try:
            with WindowsJob() as job:
                process=native()([PYTHON,'-u','-c',code],cwd=cwd,env=environment(),job=job)
                child=None
                try:
                    child=watch(line(process)['pid']);assert process.wait(10)==0
                    assert kernel().WaitForSingleObject(child,0)==258
                    process.close();process.close()
                    assert kernel().WaitForSingleObject(child,5000)==0 and sentinel.poll() is None
                    with pytest.raises(RuntimeError,match='WINDOWS_PROCESS_CLOSED'):process.poll()
                finally:
                    process.close()
                    if child:assert kernel().CloseHandle(child)
        finally:sentinel.terminate();sentinel.wait(timeout=5)


def test_parent_death_before_resume_kills_the_suspended_child():
    cwd=folder();marker=cwd/'must-not-execute.txt'
    code="""import json,sys,time
from ModuleFolders.Infrastructure.Platform.WindowsJob import WindowsJob
from ModuleFolders.Infrastructure.Platform.WindowsProcess import WindowsProcess
def suspended(process):
    print(json.dumps({'pid':process.pid}),flush=True)
    time.sleep(300)
with WindowsJob() as job:
    WindowsProcess([sys.executable,'-c',sys.argv[1]],cwd=sys.argv[2],env={'SystemRoot':sys.argv[3]},job=job,on_suspended=suspended)
"""
    child_code='from pathlib import Path;Path('+repr(str(marker))+').write_text("bad")'
    with subprocess.Popen([PYTHON,'-u','-c',code,child_code,str(cwd),os.environ['SystemRoot']],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as owner:
        child=None
        try:
            child=watch(line(owner)['pid']);assert not marker.exists()
            owner.terminate();owner.wait(timeout=5)
            assert kernel().WaitForSingleObject(child,5000)==0 and not marker.exists()
        finally:
            if owner.poll() is None:owner.terminate();owner.wait(timeout=5)
            if child:assert kernel().CloseHandle(child)


def test_invalid_native_image_and_bad_inputs_do_not_leak_handles(subtests):
    cwd=folder();fake=cwd/'invalid.exe';fake.write_bytes(b'not a Windows executable')
    # Prime Windows' first failed image-launch path before measuring repeated
    # resource cleanup. A fresh process retains a one-time native cache.
    with WindowsJob() as job,pytest.raises(OSError,match='WINDOWS_PROCESS'):
        native()([str(fake)],cwd=cwd,env=environment(),job=job)
    baseline=handle_count()
    for _ in range(3):
        with WindowsJob() as job,pytest.raises(OSError,match='WINDOWS_PROCESS'):
            native()([str(fake)],cwd=cwd,env=environment(),job=job)
    assert handle_count()==baseline
    values=[([],environment()),([PYTHON,False],environment()),([PYTHON,'a\x00b'],environment()),
        (['relative.exe'],environment()),([PYTHON],{'Path':'a','PATH':'b'}),([PYTHON],{'K':'bad\x00value'}),
        ([PYTHON],{'A=B':'v'}),([PYTHON],{'':'v'}),([PYTHON],None)]
    for argv,env in values:
        with subtests.test(argv=argv,env=env),WindowsJob() as job,pytest.raises(ValueError,match='WINDOWS_PROCESS_INVALID_INPUT'):
            native()(argv,cwd=cwd,env=env,job=job)
    assert handle_count()==baseline


def test_wait_timeout_kill_and_closed_job_cleanup():
    cwd=folder();job=WindowsJob()
    with native()([PYTHON,'-c','import time;time.sleep(300)'],cwd=cwd,env=environment(),job=job) as process:
        with pytest.raises(subprocess.TimeoutExpired):process.wait(.01)
        assert process.poll() is None
        job.close();assert process.wait(5)==0
    job.close()


def test_unrelated_inheritable_event_handle_is_not_forwarded():
    from ModuleFolders.Infrastructure.Platform.WindowsProcess import SECURITY_ATTRIBUTES
    api=kernel();api.CreateEventW.argtypes=[ctypes.POINTER(SECURITY_ATTRIBUTES),wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR]
    api.CreateEventW.restype=wintypes.HANDLE
    attributes=SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES),None,True)
    event=api.CreateEventW(ctypes.byref(attributes),True,False,None);assert event
    code="import ctypes,sys;from ctypes import wintypes;k=ctypes.WinDLL('kernel32');k.SetEvent.argtypes=[wintypes.HANDLE];k.SetEvent.restype=wintypes.BOOL;k.SetEvent(int(sys.argv[1]))"
    try:
        with WindowsJob() as job,native()([PYTHON,'-c',code,str(event)],cwd=folder(),env=environment(),job=job) as process:
            assert process.wait(10)==0
        assert api.WaitForSingleObject(event,0)==258
    finally:assert api.CloseHandle(event)


def test_pipe_transfer_failure_closes_all_earlier_resources(monkeypatch):
    cls=native();original=cls._load_native;cwd=folder();baseline=handle_count()
    def fail_second_pipe(self):
        original(self);convert=self._open_osfhandle;calls=[]
        def open_pipe(*args):
            calls.append(1)
            if len(calls)==2:raise OSError('injected pipe transfer')
            return convert(*args)
        self._open_osfhandle=open_pipe
    monkeypatch.setattr(cls,'_load_native',fail_second_pipe)
    for _ in range(3):
        with WindowsJob() as job,pytest.raises(OSError,match='WINDOWS_PROCESS_PIPE_OPEN'):
            cls([PYTHON,'-c','import time;time.sleep(300)'],cwd=cwd,env=environment(),job=job)
    assert handle_count()==baseline


def test_post_resume_thread_close_failure_terminates_already_spawned_descendants():
    handles=[];cwd=folder()
    code="import json,os,subprocess,sys,time;child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);print(json.dumps({'child':os.getpid(),'grandchild':child.pid}),flush=True);time.sleep(300)"
    def inject(process):
        handles.append(watch(process.pid));original=process._close_handle;failed=[]
        def close(handle):
            if handle==process._thread_handle and not failed:
                proof=line(process);assert proof['child']==process.pid
                handles.append(watch(proof['grandchild']));failed.append(True)
                ctypes.set_last_error(5);return False
            return original(handle)
        process._close_handle=close
    try:
        with WindowsJob() as job:
            with pytest.raises(OSError,match='WINDOWS_PROCESS_THREAD_CLOSE'):
                native()([PYTHON,'-u','-c',code],cwd=cwd,env=environment(),job=job,on_suspended=inject)
            # Assert before closing job: rollback itself must stop descendants.
            assert len(handles)==2 and all(kernel().WaitForSingleObject(h,5000)==0 for h in handles)
    finally:
        for handle in handles:assert kernel().CloseHandle(handle)
