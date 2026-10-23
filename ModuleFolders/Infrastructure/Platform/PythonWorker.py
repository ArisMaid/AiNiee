"""Serve one framed request while the control thread can acknowledge cancel."""
import os
import io
import sys
import threading

from .WorkerProtocol import encode,message,parse,validate


def serve(initial,processor,*,result_limit,error_formatter,reader=None):
    """Memory-only worker entry: flush one answer then exit without daemon joins.

    Vendored code stays on the main thread for native-extension compatibility.
    A control thread can publish cancellation independently of redirected
    stdout. This entry deliberately does not return to Python teardown.
    """
    validate(initial,'request');publication=threading.Lock();sent=False
    # Vendored code redirects sys.stdout globally while it runs. Hold the real
    # protocol streams before starting that thread, including on cancellation.
    if reader is None:
        from .ProtocolInput import ProtocolInput
        reader=ProtocolInput(sys.stdin.buffer)
    stdout=sys.stdout.buffer
    # The protocol owns stdin exclusively. Vendored code may call input(), but
    # must never compete with the controller or consume a cancellation frame.
    sys.stdin=io.StringIO('')
    def finish(body,code):
        nonlocal sent
        with publication:
            if sent:return
            sent=True
            try:
                if not isinstance(body,dict) or len(encode(body,result_limit+1))-1>result_limit:
                    body={'ok':False,'error':'WORKER_OUTPUT_LIMIT'}
            except ValueError:body={'ok':False,'error':'WORKER_OUTPUT_LIMIT'}
            payload=encode(message(initial,'result',body),result_limit+65536)
            stdout.write(payload);stdout.flush();os._exit(code)
    def controls():
        try:
            raw=reader.readline(65537)
            if not raw or len(raw)>65536:raise ValueError('WORKER_CONTROL_EOF_OR_OVERSIZE')
            validate(parse(raw,65536),'cancel',initial)
        except BaseException:finish({'ok':False,'error':'WORKER_CONTROL_INVALID'},1)
        else:finish({'ok':False,'cancelled':True,'error':'WORKER_CANCELLED'},2)
    threading.Thread(target=controls,name='backend-control',daemon=True).start()
    try:body=processor(initial['payload'])
    except BaseException as error:
        try:detail=error_formatter(error)
        except BaseException:detail=type(error).__name__
        body={'ok':False,'error':str(detail)[:512]}
    finish(body,0)
