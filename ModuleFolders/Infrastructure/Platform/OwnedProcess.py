"""Bounded binary I/O and explicit lifetime for one worker process tree."""
from contextlib import contextmanager
from contextvars import ContextVar
import math
import os
import queue
import subprocess
import threading
import time

_CHECK=ContextVar('rpg_worker_check',default=None)
_JOB=ContextVar('rpg_worker_job',default='')


@contextmanager
def worker_control(check,job_id=''):
    """Check cancellation while a worker runs; pause is acknowledged at its boundary."""
    if check is not None and not callable(check):raise ValueError('WORKER_CHECK_INVALID')
    tokens=(_CHECK.set(check),_JOB.set(job_id))
    try:yield
    finally:_JOB.reset(tokens[1]);_CHECK.reset(tokens[0])


def worker_job_id():return _JOB.get()


class OutputLimitExceeded(ValueError):pass


def _write_all(stream,payload):
    view=memoryview(payload)
    while view:
        size=stream.write(view)
        if not isinstance(size,int) or size<=0:raise OSError('WORKER_STDIN_INCOMPLETE')
        view=view[size:]
    stream.flush()


def run(argv,*,input=b'',cwd,env,timeout,stdout_limit=32*1024*1024,stderr_limit=1024*1024,
        check=None,keep_stdin=False,cancel_payload=None,cancel_grace=.25):
    """Return CompletedProcess; Windows 10+ owns descendants before first instruction.

    A framed worker keeps stdin open for a matching cancel message. Tools such
    as Tesseract receive EOF after input and use Job termination on cancellation.
    Other platforms retain subprocess semantics; Windows is the delivery target.
    """
    if not isinstance(input,bytes):raise ValueError('WORKER_INPUT_INVALID')
    for name,value in (('timeout',timeout),('cancel_grace',cancel_grace)):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
            raise ValueError('WORKER_'+name.upper()+'_INVALID')
    for value in (stdout_limit,stderr_limit):
        if type(value) is not int or value<1:raise ValueError('WORKER_OUTPUT_LIMIT_INVALID')
    if cancel_payload is not None and (not keep_stdin or not isinstance(cancel_payload,bytes)):
        raise ValueError('WORKER_CANCEL_INPUT_INVALID')
    check=check if check is not None else _CHECK.get()
    if check is not None and not callable(check):raise ValueError('WORKER_CHECK_INVALID')
    if check:check()
    if os.name!='nt':
        if keep_stdin:raise OSError('WORKER_FRAMED_PROCESS_WINDOWS_REQUIRED')
        result=subprocess.run(argv,input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            cwd=cwd,env=env,shell=False,timeout=timeout)
        if len(result.stdout)>stdout_limit or len(result.stderr)>stderr_limit:
            raise OutputLimitExceeded('WORKER_OUTPUT_LIMIT')
        if check:check()
        return result
    from .WindowsJob import WindowsJob
    from .WindowsProcess import WindowsProcess
    deadline=time.monotonic()+timeout
    with WindowsJob() as job,WindowsProcess(argv,cwd=cwd,env=env,job=job) as process:
        streams={'stdout':bytearray(),'stderr':bytearray()};limits={'stdout':stdout_limit,'stderr':stderr_limit}
        overflow=threading.Event();io_errors=[];input_complete=threading.Event();requests=queue.Queue();threads=[]
        requests.put(input)
        def read(name):
            try:
                stream=getattr(process,name)
                while True:
                    block=stream.read(65536)
                    if not block:break
                    remaining=limits[name]-len(streams[name])
                    streams[name].extend(block[:max(0,remaining)])
                    if len(block)>remaining:overflow.set();break
            except BaseException as error:io_errors.append((name,error))
        def write():
            try:
                _write_all(process.stdin,requests.get());input_complete.set()
                if keep_stdin:
                    while (payload:=requests.get()) is not None:_write_all(process.stdin,payload)
            except (BrokenPipeError,OSError) as error:io_errors.append(('stdin',error))
            finally:
                try:process.stdin.close()
                except OSError as error:io_errors.append(('stdin',error))
        for name in ('stdout','stderr'):
            thread=threading.Thread(target=read,args=(name,),name='rpg-worker-'+name,daemon=True);threads.append(thread);thread.start()
        writer=threading.Thread(target=write,name='rpg-worker-stdin',daemon=True);threads.append(writer);writer.start()
        failure=None;cleanup_errors=[]
        try:
            while True:
                if overflow.is_set():raise OutputLimitExceeded('WORKER_OUTPUT_LIMIT')
                status=process.poll()
                if status is not None:break
                if time.monotonic()>=deadline:raise subprocess.TimeoutExpired(tuple(argv),timeout)
                if check:check()
                time.sleep(.01)
            if check:check()
        except BaseException as error:
            failure=error
            if cancel_payload is not None:
                requests.put(cancel_payload)
                grace=time.monotonic()+cancel_grace
                try:
                    while process.poll() is None and time.monotonic()<grace:time.sleep(.01)
                except BaseException as stop_error:cleanup_errors.append(stop_error)
            raise
        finally:
            # Close the whole job before waiting for pipe EOF: a descendant may
            # inherit stdout after the primary has returned successfully.
            try:job.terminate(1)
            except BaseException as error:cleanup_errors.append(error)
            requests.put(None)
            try:process.wait(5)
            except BaseException as error:cleanup_errors.append(error)
            for thread in threads:thread.join(5)
            if any(t.is_alive() for t in threads):cleanup_errors.append(RuntimeError('WORKER_IO_THREAD_STUCK'))
            if isinstance(failure,subprocess.TimeoutExpired):
                failure.output=bytes(streams['stdout']);failure.stderr=bytes(streams['stderr'])
            if cleanup_errors and failure is None:raise cleanup_errors[0]
        if overflow.is_set():raise OutputLimitExceeded('WORKER_OUTPUT_LIMIT')
        if not input_complete.is_set() and process.returncode==0:raise OSError('WORKER_STDIN_INCOMPLETE')
        unexpected=next((e for name,e in io_errors if name!='stdin'),None)
        if unexpected is not None:raise OSError('WORKER_IO_FAILED') from unexpected
        return subprocess.CompletedProcess(tuple(argv),process.returncode,bytes(streams['stdout']),bytes(streams['stderr']))
