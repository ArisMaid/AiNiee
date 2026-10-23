"""Protected: registered output stages are retained, never trusted as checkpoints."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
from unittest.mock import patch
import pytest
from ModuleFolders.Service.GameProject import PathGuard
from ModuleFolders.Service.GameProject.BuildJournal import BuildJournal
from ModuleFolders.Service.GameProject.BuildService import BuildService,file_hash
from ModuleFolders.Service.GameProject.GameProjectService import GameProjectService


@pytest.fixture
def service(tmp_path):
    source=tmp_path/'source';(source/'data').mkdir(parents=True);(source/'js').mkdir()
    (source/'a.bin').write_bytes(b'unchanged prefix')
    (source/'index.html').write_text('<title>synthetic</title>',encoding='utf-8')
    (source/'js/rmmz_core.js').write_text('// rmmz_core.js v1.7.0',encoding='utf-8')
    (source/'data/System.json').write_text(json.dumps({'gameTitle':'テスト','advanced':{'gameId':1}}),encoding='utf-8')
    (source/'data/Items.json').write_text(json.dumps([None,{'id':1,'name':'回復薬','description':'説明'}]),encoding='utf-8')
    with GameProjectService.create(source,tmp_path/'project') as current:
        current.extract();unit=next(u for u in current.store.units() if u.source_text=='回復薬')
        assert current.import_translations({unit.unit_id:'恢复药甲'})[0].status=='accepted'
        yield current,unit,source


def latest(service,operation='BUILD'):
    return next(j for j in reversed(service.store.jobs()) if j['operation']==operation)


@pytest.mark.skipif(os.name!='nt',reason='Native Windows file sharing failure')
def test_failed_native_atomic_replace_can_resume_frozen_build_and_keep_manual_edit(service,tmp_path,monkeypatch):
    current,unit,source=service;originals={p.relative_to(source).as_posix():file_hash(p) for p in source.rglob('*') if p.is_file()}
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    api.CreateFileW.restype=wintypes.HANDLE;api.CloseHandle.argtypes=[wintypes.HANDLE]
    handles=[];actual_replace=os.replace
    def locked_replace(stage,target):
        target=Path(target)
        if target.name=='Items.json' and not handles:
            handle=api.CreateFileW(str(target),0x80000000,3,None,3,0x80,None)
            assert handle!=ctypes.c_void_p(-1).value;handles.append(handle)
        return actual_replace(stage,target)
    try:
        with monkeypatch.context() as fault:
            fault.setattr(os,'replace',locked_replace)
            fault.setattr(PathGuard.time,'sleep',lambda _:None)
            with pytest.raises(PermissionError):current.build(tmp_path/'output',test=True)
    finally:
        for handle in handles:api.CloseHandle(handle)
    old=latest(current);assert old['run_state']=='FAILED';build_id=old['result']['build_id']
    staging=Path(old['result']['staging']);temporary=next(staging.glob('data/.Items.json.*.staging'))
    abandoned=temporary.read_bytes()
    assert current.import_translations({unit.unit_id:'人工保留乙'})[0].status=='accepted'
    current.store.set_locked(unit.unit_id,True)
    result=current.resume_build(build_id)
    assert BuildService.verify(result['output_path'])['passed'] and result['recovery']['reused_files']>=1
    assert json.loads((Path(result['output_path'])/'data/Items.json').read_text(encoding='utf-8'))[1]['name']=='恢复药甲'
    assert current.store.translation(unit.unit_id)['text']=='人工保留乙' and current.store.translation(unit.unit_id)['manual_locked']
    assert current.store.get_job(old['job_id'])['run_state']=='FAILED'
    retained=[current.store.root/p for p in result['recovery']['retained_files']]
    assert any(p.read_bytes()==abandoned for p in retained)
    assert not temporary.exists()
    assert {p.relative_to(source).as_posix():file_hash(p) for p in source.rglob('*') if p.is_file()}==originals


@pytest.fixture
def writer_case(tmp_path):
    from ModuleFolders.Service.GameProject.BuildAtomicWriter import BuildAtomicWriter
    project=tmp_path/'project';records=project/'builds'/uuid.uuid4().hex;records.mkdir(parents=True)
    build_id=records.name;output=tmp_path/'output';staging=output/('.staging-'+build_id);(staging/'data').mkdir(parents=True)
    source=tmp_path/'source';source.mkdir()
    descriptor={'schema_version':1,'build_id':build_id,'project_id':'pending','output_root':str(output),
        'source_root':str(source),'test':True,'runtime_capture':False,'frozen_sha256':'a'*64,'plan_digest':'b'*64}
    with BuildJournal.create(project,build_id,descriptor) as journal:
        attempt=journal.new_attempt(uuid.uuid4().hex)
        writer=BuildAtomicWriter(journal,attempt,{'data/Items.json'})
        yield journal,writer,staging/'data/Items.json',BuildAtomicWriter


def leave_registered_stage(writer,target,payload=b'complete new payload'):
    target.write_bytes(b'old target')
    with patch.object(PathGuard,'_replace_overwrite_with_retry',side_effect=OSError('injected before replace')):
        with pytest.raises(OSError,match='injected'):writer.write(target,payload,overwrite=True)
    stages=list(target.parent.glob('.*.staging'));assert len(stages)==1
    return stages[0]


@pytest.mark.parametrize('partial',[False,True])
def test_registered_complete_or_partial_stage_is_preserved_and_idempotent(writer_case,partial):
    journal,writer,target,Writer=writer_case;stage=leave_registered_stage(writer,target)
    if partial:stage.write_bytes(b'partial')
    expected=stage.read_bytes();paths=writer.recover()
    assert len(paths)==1 and (journal.project_root/paths[0]).read_bytes()==expected
    assert target.read_bytes()==b'old target' and not stage.exists()
    assert writer.recover()==paths
    proofs=list((journal.records_root/'atomic-recovery').glob('*.json'));assert len(proofs)==1
    proof=json.loads(proofs[0].read_text(encoding='utf-8'))
    assert proof['actual_sha256']==hashlib.sha256(expected).hexdigest() and proof['actual_size']==len(expected)


def test_rename_then_crash_is_reconciled_from_durable_proof(writer_case,monkeypatch):
    journal,writer,target,Writer=writer_case;stage=leave_registered_stage(writer,target)
    rename=os.rename
    def move_then_crash(source,destination):
        rename(source,destination)
        if Path(destination).parent.name=='atomic-retained':
            raise RuntimeError('simulated crash after rename')
    with monkeypatch.context() as crash:
        crash.setattr(os,'rename',move_then_crash)
        with pytest.raises(RuntimeError,match='after rename'):writer.recover()
    assert not stage.exists()
    paths=writer.recover();assert len(paths)==1
    assert (journal.project_root/paths[0]).read_bytes()==b'complete new payload'


def test_unknown_matching_stage_is_never_adopted(writer_case):
    journal,writer,target,Writer=writer_case;stage=leave_registered_stage(writer,target)
    unknown=target.parent/('.Items.json.'+uuid.uuid4().hex+'.staging');unknown.write_bytes(stage.read_bytes())
    paths=writer.recover();assert len(paths)==1
    assert unknown.read_bytes()==b'complete new payload' and target.read_bytes()==b'old target'


@pytest.mark.parametrize('field,value',[('attempt_id','f'*32),('build_id','f'*32),
    ('plan_digest','f'*64),('frozen_sha256','f'*64),('temporary','../escape'),('target','data/Other.json'),
    ('schema_version',True),('payload_size',True)])
def test_invalid_marker_binding_is_rejected_before_any_move(writer_case,field,value):
    journal,writer,target,Writer=writer_case;stage=leave_registered_stage(writer,target)
    marker=next((journal.records_root/'atomic-writes').glob('*.json'))
    data=json.loads(marker.read_text(encoding='utf-8'));data[field]=value;marker.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError):writer.recover()
    assert stage.read_bytes()==b'complete new payload' and target.read_bytes()==b'old target'


def test_existing_recovery_proof_cannot_be_rewritten_to_accept_changed_bytes(writer_case,monkeypatch):
    journal,writer,target,Writer=writer_case;stage=leave_registered_stage(writer,target)
    rename=os.rename
    def fail_only_archive(source,destination):
        if Path(destination).parent.name=='atomic-retained':raise OSError('before rename')
        return rename(source,destination)
    with monkeypatch.context() as crash:
        crash.setattr(os,'rename',fail_only_archive)
        with pytest.raises(OSError,match='before rename'):writer.recover()
    proof=next((journal.records_root/'atomic-recovery').glob('*.json'));before=proof.read_bytes()
    stage.write_bytes(b'changed since proof')
    with pytest.raises(ValueError):writer.recover()
    assert proof.read_bytes()==before and stage.read_bytes()==b'changed since proof'


@pytest.mark.parametrize('bad',[True,'../escape','A'*32,'a'*31])
def test_preallocated_atomic_stage_id_is_validated_before_creating_files(tmp_path,bad):
    path=tmp_path/'not-created/data.json'
    with pytest.raises(PathGuard.PathViolation):PathGuard.atomic_write(path,b'data',staging_id=bad)
    assert not path.parent.exists()


def test_write_does_not_normalize_dot_segments_into_an_allowed_target(writer_case):
    journal,writer,target,Writer=writer_case
    alias=str(target.parent/'..'/'data'/target.name)
    with pytest.raises(ValueError):writer.write(alias,b'payload')
    assert not (journal.records_root/'atomic-writes').exists()


@pytest.mark.parametrize('raw',[b'{"schema_version":1,"schema_version":1}',
    b'['*1200+b']'*1200,b'x'*16385,b'{"schema_version":NaN}'])
def test_malformed_or_unbounded_marker_never_moves_registered_bytes(writer_case,raw):
    journal,writer,target,Writer=writer_case;stage=leave_registered_stage(writer,target)
    marker=next((journal.records_root/'atomic-writes').glob('*.json'));marker.write_bytes(raw)
    with pytest.raises(ValueError):writer.recover()
    assert stage.read_bytes()==b'complete new payload' and target.read_bytes()==b'old target'


def test_all_markers_are_validated_before_the_first_archive(writer_case):
    journal,writer,target,Writer=writer_case;first=leave_registered_stage(writer,target)
    with patch.object(PathGuard,'_replace_overwrite_with_retry',side_effect=OSError('second stage')):
        with pytest.raises(OSError):writer.write(target,b'second payload',overwrite=True)
    markers=list((journal.records_root/'atomic-writes').glob('*.json'));assert len(markers)==2
    markers[-1].write_text('{"invalid":true}',encoding='utf-8')
    with pytest.raises(ValueError):writer.recover()
    assert len(list(target.parent.glob('.*.staging')))==2 and first.exists()
    assert not list((journal.records_root/'atomic-retained').glob('*.bin'))
