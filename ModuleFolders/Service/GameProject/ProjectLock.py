"""OS-managed persistent lock file: release the handle, never remove the file."""
from __future__ import annotations
import os
import re
from pathlib import Path
from .PathGuard import safe_join


class ProjectLock:
    def __init__(self, root):
        self.path=safe_join(root,'.game-project.lock')
        self.handle=None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        handle=open(self.path,'a+b')
        handle.seek(0,os.SEEK_END)
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise ValueError('PROJECT_BUSY: another operation owns this project') from exc
        self.handle=handle
        return self

    def __exit__(self,*_):
        if self.handle is None:return
        self.handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
        finally:self.handle.close();self.handle=None


class JobLease(ProjectLock):
    """An OS lease remains held while a model request is in flight."""
    def __init__(self, root, job_id):
        if not isinstance(job_id,str) or not re.fullmatch('[a-f0-9]{32}',job_id):
            raise ValueError('JOB_ID_INVALID')
        self.path=safe_join(root,f'jobs/{job_id}/execution.lock')
        self.handle=None


def project_write(method):
    from functools import wraps
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        with ProjectLock(self.store.root):return method(self,*args,**kwargs)
    return wrapped
