"""One-request JSON-lines protocol bound to exact request and job identities."""
import json
import re
import uuid

VERSION=1
REQUEST_LIMIT=16*1024*1024+65536


class ProtocolError(ValueError):pass


def _bad():return ProtocolError('WORKER_PROTOCOL_INVALID')


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise _bad()
        result[key]=value
    return result


def _constant(value):raise _bad()


def parse(data,limit):
    if not isinstance(data,bytes) or len(data)>limit:raise _bad()
    try:return json.loads(data.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant)
    except (ValueError,UnicodeError,RecursionError) as error:raise _bad() from error


def validate(frame,kind,expected=None):
    keys={'protocol_version','request_id','job_id','type'}|({'payload'} if kind in {'request','result'} else set())
    if (kind not in {'request','cancel','result'} or not isinstance(frame,dict) or set(frame)!=keys
            or type(frame.get('protocol_version')) is not int or frame['protocol_version']!=VERSION
            or frame.get('type')!=kind or not isinstance(frame.get('request_id'),str)
            or not re.fullmatch('[a-f0-9]{32}',frame['request_id'])
            or not isinstance(frame.get('job_id'),str) or not 0<len(frame['job_id'])<=128
            or any(c in frame['job_id'] for c in '\x00\r\n')
            or (kind in {'request','result'} and not isinstance(frame.get('payload'),dict))):raise _bad()
    if expected and any(frame[k]!=expected[k] for k in ('protocol_version','request_id','job_id')):raise _bad()
    return frame


def request(payload,job_id=''):
    identifier=uuid.uuid4().hex
    return validate(dict(protocol_version=VERSION,request_id=identifier,job_id=job_id or identifier,type='request',payload=payload),'request')


def message(initial,kind,payload=None):
    value={key:initial[key] for key in ('protocol_version','request_id','job_id')};value['type']=kind
    if kind=='result':value['payload']=payload
    return validate(value,kind,initial)


def encode(frame,limit):
    try:data=json.dumps(frame,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')+b'\n'
    except (ValueError,TypeError,RecursionError) as error:raise _bad() from error
    if len(data)>limit:raise _bad()
    return data


def response(data,initial,limit):
    if not data.endswith(b'\n') or data.count(b'\n')!=1:raise _bad()
    return validate(parse(data,limit),'result',initial)['payload']


def run_json_worker(argv,payload,*,cwd,env,timeout,stdout_limit=32*1024*1024,stderr_limit=1024*1024):
    import os
    import subprocess
    from .OwnedProcess import run,worker_job_id
    if os.name!='nt':
        # Preserve the earlier flat protocol on non-Windows source checkouts.
        return run(argv,input=json.dumps(payload,ensure_ascii=False).encode('utf-8'),cwd=cwd,env=env,
            timeout=timeout,stdout_limit=stdout_limit,stderr_limit=stderr_limit)
    initial=request(payload,worker_job_id())
    result=run(argv,input=encode(initial,REQUEST_LIMIT),cwd=cwd,env=env,timeout=timeout,
        stdout_limit=stdout_limit+65536,stderr_limit=stderr_limit,keep_stdin=True,
        cancel_payload=encode(message(initial,'cancel'),65536))
    body=response(result.stdout,initial,stdout_limit+65536)
    encoded=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(encoded)>stdout_limit:
        from .OwnedProcess import OutputLimitExceeded
        raise OutputLimitExceeded('WORKER_OUTPUT_LIMIT')
    return subprocess.CompletedProcess(result.args,result.returncode,encoded,result.stderr)
