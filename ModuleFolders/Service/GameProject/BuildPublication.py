"""Bounded Windows sharing retries for publishing one validated staging tree."""
from pathlib import Path
import re
import time
from .PathGuard import safe_join

_DELAYS=(.03,.06,.12,.24,.48)
_WINDOWS_TRANSIENT=frozenset((5,32,33))


def publish_staging(staging,final):
    """Rename one build-owned sibling directory, never replace an output.

    Paths stay in the explicitly selected output parent. Windows rename keeps
    its no-replace behavior; access/sharing errors receive a bounded retry and
    persistent refusal leaves the staging directory for normal build recovery.
    """
    staging=Path(staging).absolute();final=Path(final).absolute()
    identity=re.fullmatch(r'\.staging-([a-f0-9]{32})',staging.name)
    if (not identity or staging.parent!=final.parent or
            final.name!='game-zh-CN-'+identity.group(1)):
        raise ValueError('BUILD_PUBLICATION_PATH_INVALID')
    parent=staging.parent
    for attempt in range(len(_DELAYS)+1):
        source=safe_join(parent,staging.name,must_exist=True)
        target=safe_join(parent,final.name)
        if not source.is_dir():raise ValueError('BUILD_STAGING_MISSING')
        if target.exists():raise FileExistsError(target)
        try:
            source.rename(target)
            return
        except OSError as error:
            if getattr(error,'winerror',None) not in _WINDOWS_TRANSIENT or attempt==len(_DELAYS):raise
            time.sleep(_DELAYS[attempt])
