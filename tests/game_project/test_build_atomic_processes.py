"""Real Windows process exits at registered stage/retention boundaries."""
import hashlib
import json
import os
from pathlib import Path
import sys
import pytest
from test_build_atomic_recovery import service,latest
from ModuleFolders.Infrastructure.Platform.OwnedProcess import run as owned_run
from ModuleFolders.Service.GameProject.BuildService import BuildService,file_hash

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Native owned Windows process exit')
ROOT=Path(__file__).resolve().parents[2]
CHILD=r'''
import os,sys
from pathlib import Path
from ModuleFolders.Service.GameProject import PathGuard
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService
mode,project,output= sys.argv[1:]
if mode=='archive_exit':
    rename=os.rename
    def exit_after_archive(source,destination):
        result=rename(source,destination)
        if Path(destination).parent.name=='atomic-retained':os._exit(36)
        return result
    os.rename=exit_after_archive
    with GameProjectService(project) as current:current.resume_build(output)
else:
    replace=PathGuard._replace_overwrite_with_retry
    def exit_before_replace(stage,target):
        if Path(target).name=='Items.json':
            if mode=='partial':Path(stage).write_bytes(b'partial crash payload')
            os._exit(35)
        return replace(stage,target)
    PathGuard._replace_overwrite_with_retry=exit_before_replace
    with GameProjectService(project) as current:current.build(output,test=True)
'''


def child(case,mode,project,output,expected):
    case.mkdir();script=case/'crash-builder.py';script.write_text(CHILD,encoding='utf-8')
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP','COMSPEC'}}
    env.update(PATH=str(Path(os.environ['SystemRoot'])/'System32'),PYTHONPATH=str(ROOT),
        PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',AINIEE_OFFLINE='1')
    result=owned_run([sys.executable,str(script),mode,str(project),str(output)],cwd=case,env=env,input=b'',timeout=20)
    (case/'stdout.log').write_bytes(result.stdout);(case/'stderr.log').write_bytes(result.stderr)
    assert result.returncode==expected,(result.returncode,result.stderr[-1800:])


@pytest.mark.parametrize('mode',['complete','partial','archive_exit'])
def test_real_process_exit_retains_registered_bytes_and_resumes_same_frozen_build(service,tmp_path,mode):
    current,unit,source=service
    originals={p.relative_to(source).as_posix():file_hash(p) for p in source.rglob('*') if p.is_file()}
    child(tmp_path/'first-crash','partial' if mode=='partial' else 'complete',current.store.root,tmp_path/'output',35)
    old=latest(current);assert old['run_state']=='RUNNING';build_id=old['result']['build_id']
    staging=Path(old['result']['staging']);stage=next(staging.glob('data/.Items.json.*.staging'))
    retained_bytes=stage.read_bytes()
    assert retained_bytes==b'partial crash payload' if mode=='partial' else b'\xe6\x81\xa2\xe5\xa4\x8d' in retained_bytes
    if mode=='archive_exit':
        child(tmp_path/'second-crash','archive_exit',current.store.root,build_id,36)
        assert not stage.exists()
    assert current.import_translations({unit.unit_id:'人工保留乙'})[0].status=='accepted'
    current.store.set_locked(unit.unit_id,True)
    result=current.resume_build(build_id)
    assert result['build_id']==build_id and result['recovery']['reused_files']>=1
    assert BuildService.verify(result['output_path'])['passed']
    assert json.loads((Path(result['output_path'])/'data/Items.json').read_text(encoding='utf-8'))[1]['name']=='恢复药甲'
    assert current.store.translation(unit.unit_id)['text']=='人工保留乙' and current.store.translation(unit.unit_id)['manual_locked']
    assert current.store.get_job(old['job_id'])['run_state']=='INTERRUPTED'
    assert any((current.store.root/relative).read_bytes()==retained_bytes for relative in result['recovery']['retained_files'])
    assert not stage.exists() and not list(Path(result['output_path']).rglob('*.staging'))
    assert {p.relative_to(source).as_posix():file_hash(p) for p in source.rglob('*') if p.is_file()}==originals
