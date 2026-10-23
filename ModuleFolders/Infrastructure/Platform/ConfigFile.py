"""Atomic config replacement with bounded Windows sharing-error recovery.

Never deletes a file. A failed write retains its unique temporary file and
propagates the error; it never truncates or replaces the previous config early.
This does not provide cross-process read/modify/write conflict resolution.
"""
import os
from pathlib import Path
import time
import uuid

_DELAYS=(0.03,0.06,0.12,0.24,0.48)
_WINDOWS_RETRY_ERRORS=frozenset((5,32,33))


def write_config_text(path,text):
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('x',encoding='utf-8') as writer:
        writer.write(text)
        writer.flush()
        os.fsync(writer.fileno())
    for attempt in range(len(_DELAYS)+1):
        try:
            os.replace(temporary,target)
            return
        except OSError as error:
            if getattr(error,'winerror',None) not in _WINDOWS_RETRY_ERRORS or attempt==len(_DELAYS):
                raise
            time.sleep(_DELAYS[attempt])
