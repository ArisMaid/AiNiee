"""Read-only verification of a completed output owned by the current project."""
from pathlib import Path
import hashlib
import re
from .BuildService import _strict_json,source_file_set
from .PathGuard import assert_disjoint,safe_join

_IDENTITY=('build_id','project_id','input_digest','output_path')


def inspect_registered_build(store,reference,*,progress=None,control=None):
    """Verify one captured UI reference against SQLite and actual output bytes.

    No project writes, game launch, URL dispatch or runtime-pass annotation.
    The caller performs this potentially long read on its background worker.
    """
    current=store.latest_build_summary()
    if not isinstance(reference,dict) or not current or any(reference.get(k)!=current.get(k) for k in _IDENTITY):
        raise ValueError('BUILD_REFERENCE_CHANGED: 构建记录已变化，请刷新工程后重试')
    identity=current.get('build_id');root_text=current.get('output_path')
    if (not isinstance(identity,str) or re.fullmatch('[a-f0-9]{32}',identity) is None or
            current.get('project_id')!=store.metadata()['project_id'] or
            not isinstance(root_text,str) or not Path(root_text).is_absolute()):
        raise ValueError('BUILD_REFERENCE_INVALID: 此记录没有当前工程的有效完成副本')
    root=Path(root_text)
    if root.name!='game-zh-CN-'+identity:
        raise ValueError('BUILD_OUTPUT_INVALID: 完成副本的目录名称与构建记录不符')
    assert_disjoint(root,store.root,store.metadata()['source_root'])
    manifest_path=safe_join(root,'rpg-build-manifest.json',must_exist=True)
    marker_path=safe_join(root,'rpg-build-complete.json',must_exist=True)
    manifest_bytes=manifest_path.read_bytes();marker_bytes=marker_path.read_bytes()
    manifest=_strict_json(manifest_bytes);marker=_strict_json(marker_bytes)
    expected=store.get_build_record(identity)
    if expected is None:raise ValueError('BUILD_REFERENCE_CHANGED: 构建登记不存在')
    expected=dict(expected);expected.pop('recorded_at',None)
    if manifest!=expected:
        raise ValueError('BUILD_MANIFEST_CHANGED: 副本清单与工程内的构建登记不符')
    if marker.get('build_id')!=identity or marker.get('input_digest')!=current['input_digest']:
        raise ValueError('BUILD_MARKER_MISMATCH: 完成标记与构建登记不符')
    # Runtime saves/logs are excluded by the same explicit policy as builds.
    wanted={entry['path'] for entry in manifest['files']}|{'rpg-build-manifest.json','rpg-build-complete.json'}
    if control:control.check(force=True)
    extra=sorted(source_file_set(root)-wanted)
    changed=[]
    for index,entry in enumerate(manifest['files']):
        if control:control.check()
        digest=hashlib.sha256()
        with safe_join(root,entry['path'],must_exist=True).open('rb') as reader:
            for chunk in iter(lambda:reader.read(1024*1024),b''):
                if control:control.check()
                digest.update(chunk)
        if digest.hexdigest()!=entry['output_sha256']:changed.append(entry['path'])
        if progress:progress(index+1,len(manifest['files']),entry['path'])
        if control:control.checkpoint('hashing',index+1)
    if manifest_path.read_bytes()!=manifest_bytes or marker_path.read_bytes()!=marker_bytes:
        raise ValueError('BUILD_CHANGED_DURING_VERIFY: 校验过程中清单或完成标记发生变化')
    after=store.latest_build_summary()
    if not after or any(after.get(k)!=current.get(k) for k in _IDENTITY):
        raise ValueError('BUILD_REFERENCE_CHANGED: 校验期间产生了新的构建，请刷新后重试')
    return {'reference':current,'passed':not changed and not extra,
        'changed_files':changed,'unexpected_files':extra,
        'runtime_validation':manifest['runtime_validation'],'output_path':str(root)}


def verify_registered_build(store,reference,*,progress=None,on_job=None):
    """Read output files while recording a controllable verification attempt."""
    from .JobControl import JobControl
    from .JobController import begin_commit
    from .ProjectLock import JobLease
    job=store.create_job('VERIFY_BUILD',{'reference':dict(reference)})
    store.update_job(job['job_id'],run_state='RUNNING',stage='preflight')
    control=JobControl(store,job['job_id'])
    with JobLease(store.root,job['job_id']):
        try:
            if on_job:on_job({'job_id':job['job_id'],'project_root':str(store.root)})
            result=inspect_registered_build(store,reference,progress=progress,control=control)
            begin_commit(store,control)
            store.update_job(job['job_id'],run_state='COMPLETED',stage='complete',
                result={k:result[k] for k in ('passed','changed_files','unexpected_files','runtime_validation')})
            return result
        except Exception as error:
            control.fail(error)
            raise
