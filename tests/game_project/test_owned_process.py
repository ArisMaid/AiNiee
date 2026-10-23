import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
from test_windows_process import PYTHON,ROOT,environment,folder,kernel,watch,native
from ModuleFolders.Infrastructure.Platform.OwnedProcess import run,worker_control,OutputLimitExceeded
from ModuleFolders.Infrastructure.Platform.WorkerProtocol import (request,message,encode,response,parse,
    validate,ProtocolError,REQUEST_LIMIT,run_json_worker)
from ModuleFolders.Infrastructure.Platform.WindowsJob import WindowsJob


class Cancelled(Exception):pass


def alive_io():return [t for t in threading.enumerate() if t.name.startswith('rpg-worker-')]


def test_bounded_runner_drains_both_pipes_and_all_stdin():
    payload=b'0123456789'*100000
    code="import sys;sys.stderr.buffer.write(b'e'*100000);sys.stderr.buffer.flush();sys.stdout.buffer.write(sys.stdin.buffer.read());sys.stdout.buffer.flush()"
    result=run([PYTHON,'-u','-c',code],input=payload,cwd=folder(),env=environment(),timeout=10,stderr_limit=200000)
    assert result.returncode==0 and result.stdout==payload and result.stderr==b'e'*100000
    assert not alive_io()


def test_output_overflow_stops_the_tree_and_reader_threads():
    started=time.monotonic()
    with pytest.raises(OutputLimitExceeded,match='WORKER_OUTPUT_LIMIT'):
        run([PYTHON,'-u','-c',"import sys,time;sys.stderr.buffer.write(b'e'*2000000);sys.stderr.buffer.flush();time.sleep(300)"],
            cwd=folder(),env=environment(),timeout=10,stderr_limit=4096)
    assert time.monotonic()-started<5 and not alive_io()


def test_timeout_stops_an_ungated_child_and_grandchild():
    cwd=folder();proof=cwd/'pids.json'
    code="import json,subprocess,sys,time;from pathlib import Path;child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);Path(sys.argv[1]).write_text(json.dumps({'pid':child.pid}));time.sleep(300)"
    handles=[]
    def observe():
        if proof.exists() and not handles:
            try:pid=json.loads(proof.read_text())['pid']
            except ValueError:return
            handles.append(watch(pid))
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run([PYTHON,'-u','-c',code,str(proof)],cwd=cwd,env=environment(),timeout=.8,check=observe)
        assert handles and kernel().WaitForSingleObject(handles[0],5000)==0 and not alive_io()
    finally:
        for handle in handles:assert kernel().CloseHandle(handle)


def test_cancel_probe_stops_tree_and_keeps_original_exception():
    cwd=folder();ready=cwd/'ready'
    code="import sys,time;from pathlib import Path;Path(sys.argv[1]).write_text('ready');time.sleep(300)"
    def check():
        if ready.exists():raise Cancelled('cancel original')
    with worker_control(check,'test-cancel'),pytest.raises(Cancelled,match='cancel original'):
        run([PYTHON,'-u','-c',code,str(ready)],cwd=cwd,env=environment(),timeout=10)
    assert not alive_io()


def test_protocol_checks_identity_duplicates_and_exact_version(subtests):
    initial=request({'operation':'extract'})
    good=message(initial,'result',{'ok':True})
    assert response(encode(good,65536),initial,65536)=={'ok':True}
    for key,value in [('protocol_version',True),('protocol_version',1.0),('request_id','a'*32),('job_id','other'),('type','request')]:
        with subtests.test(key=key,value=value):
            bad=dict(good);bad[key]=value
            with pytest.raises(ProtocolError):response(encode(bad,65536),initial,65536)
    for data in (b'{"ok":true,"ok":false}',b'{"ok":NaN}',b'\xff',b'{}\n{}\n'):
        with subtests.test(data=data),pytest.raises(ProtocolError):
            if b'\n' in data:response(data,initial,65536)
            else:parse(data,65536)


def python_server_code():
    return """import contextlib,io,sys,time
from pathlib import Path
from ModuleFolders.Infrastructure.Platform.WorkerProtocol import parse,REQUEST_LIMIT
from ModuleFolders.Infrastructure.Platform.PythonWorker import serve
from ModuleFolders.Infrastructure.Platform.ProtocolInput import ProtocolInput
reader=ProtocolInput(sys.stdin.buffer)
initial=parse(reader.readline(REQUEST_LIMIT+1),REQUEST_LIMIT)
def work(payload):
    with contextlib.redirect_stdout(io.StringIO()):
        Path(payload['marker']).write_text('running')
        time.sleep(300)
    return {'ok':True}
serve(initial,work,result_limit=65536,error_formatter=lambda e:type(e).__name__,reader=reader)
"""


def test_python_worker_cancel_ack_survives_upstream_stdout_redirection():
    cwd=folder();marker=cwd/'running';initial=request({'marker':str(marker)})
    with WindowsJob() as job,native()([PYTHON,'-u','-c',python_server_code()],cwd=ROOT,
            env=environment(),job=job) as process:
        process.stdin.write(encode(initial,REQUEST_LIMIT));process.stdin.flush()
        deadline=time.monotonic()+5
        while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
        assert marker.exists()
        process.stdin.write(encode(message(initial,'cancel'),65536));process.stdin.flush()
        assert process.wait(5)==2
        body=response(process.stdout.read(),initial,65536)
        assert body['cancelled'] is True and body['error']=='WORKER_CANCELLED'


def test_framed_python_worker_is_cancelled_through_runner_context():
    cwd=folder();marker=cwd/'running'
    def check():
        if marker.exists():raise Cancelled('framed cancellation')
    with worker_control(check,'job-framed'),pytest.raises(Cancelled,match='framed cancellation'):
        run_json_worker([PYTHON,'-u','-c',python_server_code()],{'marker':str(marker)},cwd=ROOT,env=environment(),timeout=10)
    assert not alive_io()


def test_node_worker_cancel_ack_and_wrong_identity_rejection():
    node=Path('C:/Program Files/nodejs/node.exe');worker=ROOT/'ModuleFolders/Infrastructure/GameAdapters/JsWorker/worker.cjs'
    env=dict(environment(),RPG_ACORN_PATH=str(ROOT/'.tools/js/node_modules/acorn'))
    # Cancellation enters before the parsing thread can publish a result.
    for wrong in (False,True):
        initial=request({'operation':'extract','object_path':'Words',
            'source':"const Words={text:'名前'};"+'/* padding */\n'*100000})
        cancel=message(initial,'cancel')
        if wrong:cancel['job_id']='wrong-job'
        with WindowsJob() as job,native()([str(node),str(worker)],cwd=worker.parent,env=env,job=job) as process:
            payload=encode(initial,REQUEST_LIMIT)+encode(cancel,65536)
            view=memoryview(payload)
            while view:view=view[process.stdin.write(view):]
            process.stdin.flush();assert process.wait(10)==(1 if wrong else 2)
            body=response(process.stdout.read(),initial,65536)
            assert body['error']==('WORKER_PROTOCOL_INVALID' if wrong else 'WORKER_CANCELLED')
            assert bool(body.get('cancelled')) is (not wrong)


def test_python_worker_imports_numpy_while_control_pipe_remains_open():
    # Stev imports pandas/NumPy. A blocking CRT stdin read in another thread
    # hangs that native import on the supported Windows Python runtime.
    code='''import sys
from ModuleFolders.Infrastructure.Platform.ProtocolInput import ProtocolInput
from ModuleFolders.Infrastructure.Platform.WorkerProtocol import parse,REQUEST_LIMIT
from ModuleFolders.Infrastructure.Platform.PythonWorker import serve
reader=ProtocolInput(sys.stdin.buffer)
initial=parse(reader.readline(REQUEST_LIMIT+1),REQUEST_LIMIT)
def work(payload):
    import numpy
    return {'ok':True,'native_import':numpy.__version__}
serve(initial,work,result_limit=65536,error_formatter=lambda e:type(e).__name__,reader=reader)
'''
    result=run_json_worker([sys.executable,'-u','-c',code],{},cwd=ROOT,env=environment(),timeout=8)
    assert result.returncode==0 and json.loads(result.stdout)['native_import']
    assert not alive_io()


def test_protocol_input_preserves_packed_cancel_and_rejects_wrong_job():
    for wrong in (False,True):
        cwd=folder();initial=request({'marker':str(cwd/'running')});cancel=message(initial,'cancel')
        if wrong:cancel['job_id']='another-job'
        with WindowsJob() as job,native()([PYTHON,'-u','-c',python_server_code()],cwd=ROOT,
                env=environment(),job=job) as process:
            # Both frames may be read in one OS chunk. The reader must retain
            # the second line when ownership passes to the control thread.
            payload=encode(initial,REQUEST_LIMIT)+encode(cancel,65536)
            view=memoryview(payload)
            while view:view=view[process.stdin.write(view):]
            process.stdin.flush();assert process.wait(5)==(1 if wrong else 2)
            body=response(process.stdout.read(),initial,65536)
            assert body['error']==('WORKER_CONTROL_INVALID' if wrong else 'WORKER_CANCELLED')


def test_protocol_input_split_utf8_and_bounded_eof():
    cwd=folder()
    code='''import json,sys
from ModuleFolders.Infrastructure.Platform.ProtocolInput import ProtocolInput
reader=ProtocolInput(sys.stdin.buffer)
print(json.dumps([reader.readline(4).hex(),reader.readline(10).hex(),reader.read(5).hex(),reader.read(5).hex()]),flush=True)
'''
    with WindowsJob() as job,native()([PYTHON,'-u','-c',code],cwd=ROOT,env=environment(),job=job) as process:
        payload='名前\n后续'.encode('utf-8')
        process.stdin.write(payload[:1]);process.stdin.flush();time.sleep(.05)
        process.stdin.write(payload[1:]);process.stdin.close()
        assert process.wait(5)==0
        assert json.loads(process.stdout.read())==[payload[:4].hex(),payload[4:7].hex(),payload[7:12].hex(),payload[12:].hex()]


def test_protocol_input_memory_fallback_and_limits():
    import io
    from ModuleFolders.Infrastructure.Platform.ProtocolInput import ProtocolInput
    stream=io.BytesIO(b'abc\ndefgh\n');reader=ProtocolInput(stream)
    assert reader.readline(2)==b'ab'
    assert reader.readline(10)==b'c\n'
    assert reader.read(3)==b'def'
    assert reader.read(10)==b'gh\n'
    assert reader.readline(1)==b'' and not stream.closed
    for bad in (-1,0,True,None,1.5):
        with pytest.raises((TypeError,ValueError)):reader.readline(bad)
