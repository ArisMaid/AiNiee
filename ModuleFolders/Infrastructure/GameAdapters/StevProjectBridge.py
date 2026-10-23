"""Owned whole-work-copy Stev directory entry with independent parent proofs.

Inputs are explicit files, never a game-root parameter sent to the SDK. Every
file is cloned before a fresh worker can call real ReadGame/InjectGame. Only
outputs whose full semantics match the approved native plan become candidates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

from ModuleFolders.Service.GameProject.PathGuard import safe_join,atomic_write
from . import CompatibilityBridge as bridge
from .BackendWriters import _strict_loads,_normalize_changes,_assign_leaf,_canonical_json
from . import BackendWorker
from .StevSourceJson import parse_source_json

MAX_FILES=100000
MAX_TOTAL=32*1024**3
MAX_JSON=16*1024**2
MAX_REPORT=128*1024**2
PROJECT_TIMEOUT=300
_HEX=re.compile(r'[0-9a-f]{64}\Z')
_ROUND=re.compile(r'rounds/[0-9]{4}\Z')
_REPARSE=getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)


def _fail(code='BACKEND_PIPELINE_INVALID',detail=''):
    raise ValueError(code+(': '+detail if detail else ''))


def _hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def _regular(path):
    path=Path(path)
    info=os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or getattr(info,'st_file_attributes',0)&_REPARSE or info.st_nlink!=1:
        _fail('BACKEND_SIDE_EFFECT','file identity')
    safe_join(path.parent,path.name,must_exist=True)
    return info


def _bounded(path,limit):
    if _regular(path).st_size>limit:_fail('BACKEND_OUTPUT_LIMIT')
    with Path(path).open('rb') as handle:raw=handle.read(limit+1)
    if len(raw)>limit:_fail('BACKEND_OUTPUT_LIMIT')
    return raw


def _tree(root):
    """Reject links and return the exact file/directory set, including empty dirs."""
    root=Path(root);found={};directories=set()
    for folder,dirs,files in os.walk(root,followlinks=False):
        for name in dirs:
            p=Path(folder)/name;safe_join(root,p.relative_to(root).as_posix(),must_exist=True)
            info=os.lstat(p)
            if not stat.S_ISDIR(info.st_mode) or getattr(info,'st_file_attributes',0)&_REPARSE:
                _fail('BACKEND_SIDE_EFFECT','directory identity')
            directories.add(p.relative_to(root).as_posix())
        for name in files:
            p=Path(folder)/name;_regular(p)
            found[p.relative_to(root).as_posix()]=p
    return found,directories


def _read_json(path,limit=MAX_REPORT):
    try:return _strict_loads(_bounded(path,limit).decode('utf-8-sig'))
    except (UnicodeError,RecursionError):_fail('BACKEND_PIPELINE_INVALID','artifact JSON')


def _json(raw):
    if len(raw)>MAX_JSON:_fail('BACKEND_SOURCE_TOO_LARGE')
    try:return _strict_loads(raw.decode('utf-8-sig'))
    except (UnicodeError,RecursionError):_fail('BACKEND_SOURCE_JSON_INVALID')


def _row_paths(root,rows):
    if not isinstance(rows,list):_fail(detail='manifest')
    paths={}
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'path','size','sha256'}:_fail(detail='manifest row')
        rel=row['path']
        if not isinstance(rel,str) or rel in paths:_fail(detail='manifest duplicate')
        path=safe_join(root,rel,must_exist=True)
        if type(row['size']) is not int or row['size']<0 or not isinstance(row['sha256'],str) or not _HEX.fullmatch(row['sha256']):
            _fail(detail='manifest fields')
        if _regular(path).st_size!=row['size'] or _hash(path)!=row['sha256']:_fail('BACKEND_SOURCE_CHANGED')
        paths[rel]=path
    if set(_tree(root)[0])!=set(paths):_fail('BACKEND_SIDE_EFFECT','source file set')
    return paths


def _clone(files,root,check):
    if not isinstance(files,dict) or not 0<len(files)<=MAX_FILES:_fail('BACKEND_SOURCE_INVALID')
    paths={};seen=set();total=0
    for rel,value in files.items():
        if not isinstance(rel,str) or rel in ('','.'):_fail('BACKEND_PATH_INVALID')
        target=safe_join(root,rel)
        if target.relative_to(root).as_posix()!=rel or rel.casefold() in seen:_fail('BACKEND_PATH_INVALID')
        seen.add(rel.casefold())
        if isinstance(value,(bytes,bytearray,memoryview)):
            size=len(value)
        elif isinstance(value,(str,os.PathLike)):
            value=Path(value).absolute();size=_regular(value).st_size
            if value==root or value.is_relative_to(root):_fail('BACKEND_PATH_INVALID')
        else:_fail('BACKEND_SOURCE_INVALID')
        total+=size
        if total>MAX_TOTAL:_fail('BACKEND_SOURCE_TOO_LARGE')
        paths[rel]=(value,size,target)
    if shutil.disk_usage(root).free<total+64*1024*1024:_fail('INSUFFICIENT_DISK_SPACE_FOR_BACKEND')
    rows=[]
    for rel,(value,size,target) in sorted(paths.items()):
        check();target.parent.mkdir(parents=True,exist_ok=True);digest=hashlib.sha256()
        with target.open('xb') as write:
            if isinstance(value,(bytes,bytearray,memoryview)):
                raw=bytes(value);write.write(raw);digest.update(raw)
            else:
                with value.open('rb') as read:
                    for block in iter(lambda:read.read(1024*1024),b''):
                        check();write.write(block);digest.update(block)
            write.flush();os.fsync(write.fileno())
        if target.stat().st_size!=size:_fail('BACKEND_SOURCE_CHANGED')
        if isinstance(value,Path) and (_regular(value).st_size!=size or _hash(value)!=digest.hexdigest()):
            _fail('BACKEND_SOURCE_CHANGED')
        rows.append({'path':rel,'size':size,'sha256':digest.hexdigest()})
    return rows


def _upstream(root):
    return [{'path':name,'size':_regular(safe_join(root,name,must_exist=True)).st_size,
        'sha256':_hash(safe_join(root,name,must_exist=True))} for name in ('jtpp.py','config.yaml')]


def _run_project_worker(request,cwd):
    from ModuleFolders.Infrastructure.Platform.WorkerProtocol import run_json_worker
    from ModuleFolders.Infrastructure.Platform.OwnedProcess import OutputLimitExceeded
    args=[sys.executable,'--backend-worker'] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).with_name('BackendWorker.py'))]
    try:return run_json_worker(args,payload=request,cwd=str(cwd),env=bridge._worker_env(),
        timeout=PROJECT_TIMEOUT,stdout_limit=bridge.MAX_IO_BYTES)
    except OutputLimitExceeded:_fail('BACKEND_OUTPUT_LIMIT')
    except subprocess.TimeoutExpired:_fail('BACKEND_PROJECT_TIMEOUT')


def _program_proofs(rows,documents,discovery_only):
    if not isinstance(rows,list):_fail(detail='ProgramData rows')
    proven={}
    fields={'file','original','translation','address','labels','code','name_label','occurrences'}
    for row in rows:
        if not isinstance(row,dict) or set(row)!=fields:_fail(detail='ProgramData row fields')
        if any(not isinstance(row[k],str) for k in ('file','original','translation','address','labels','code')):
            _fail(detail='ProgramData strings')
        if type(row['name_label']) is not bool or not isinstance(row['occurrences'],list):_fail(detail='ProgramData metadata')
        addresses=row['address'].split('☆↑↓');codes=row['code'].split(',')
        for occurrence in row['occurrences']:
            if not isinstance(occurrence,dict) or set(occurrence)!={'relative_path','pointer','address','code','length','whole_string'}:
                _fail(detail='ProgramData occurrence')
            if occurrence['whole_string'] is not True:continue
            if 'data/'+row['file'].replace('\\','/') in discovery_only:_fail('BACKEND_LOCATOR_UNSUPPORTED','duplicate-key discovery')
            rel=occurrence['relative_path'];pointer=occurrence['pointer'];address=occurrence['address']
            if rel not in documents or not isinstance(pointer,str) or not isinstance(address,str):_fail(detail='ProgramData proof target')
            if rel!='data/'+row['file'].replace('\\','/') or occurrence['length']!=1 or type(occurrence['length']) is not int:
                _fail(detail='ProgramData proof owner')
            if len(addresses)!=len(codes) or addresses.count(address)!=1:_fail(detail='ProgramData address vector')
            index=addresses.index(address)
            if occurrence['code']!=codes[index] or not address.endswith('\u200b1'):_fail(detail='ProgramData code vector')
            actual,whole=BackendWorker._stev_pointer(documents[rel],address[:-2],row['file'],row['original'])
            if not whole or actual!=pointer:_fail('BACKEND_LOCATOR_UNSUPPORTED')
            key=(rel,pointer,row['original'],address,occurrence['code'])
            proven[key]=proven.get(key,0)+1
    return proven


def _validate(pipeline,response,source_rows,upstream,documents,requested,source_duplicates):
    if set(response)!={'ok','backend','operation','pid','report_path','report_sha256'} or response.get('operation')!='stev_project' or response.get('report_path')!='project-report.json':_fail(detail='response')
    report_path=pipeline/'project-report.json'
    report_raw=_bounded(report_path,MAX_REPORT)
    if hashlib.sha256(report_raw).hexdigest()!=response.get('report_sha256'):_fail(detail='report hash')
    report=_strict_loads(report_raw.decode('utf-8-sig'))
    expected_fields={'schema_version','backend','entrypoint','pid','game_root','source_files','jtpp_sha256','config_sha256',
        'effective_config','patches','program_data','rounds','source_preserved','upstream_preserved','source_duplicates'}
    if not isinstance(report,dict) or set(report)!=expected_fields:_fail(detail='report fields')
    hashes={r['path']:r['sha256'] for r in upstream}
    if (type(report['schema_version']) is not int or report['schema_version']!=1 or report['backend']!='stev' or report['entrypoint']!='Jr_Tpp.ReadGame -> Jr_Tpp.InjectGame' or
        type(report['pid']) is not int or report['pid']==os.getpid() or report['pid']<=0 or report['pid']!=response.get('pid') or
        report['game_root']!=str(pipeline/'input') or type(report['source_files']) is not int or report['source_files']!=len(source_rows) or
        report['jtpp_sha256']!=hashes['jtpp.py'] or report['config_sha256']!=hashes['config.yaml'] or
        report['source_preserved'] is not True or report['upstream_preserved'] is not True or
        report['patches']!=['utf8-sig-io','disabled-list-cleanup']):_fail(detail='report provenance')
    config=report['effective_config']
    if not isinstance(config,dict):_fail(detail='effective config')
    overrides={'ja':False,'sumcode':[],'sptext':{},'ReadCode':[],'BlackDir':[],'BlackCode':[],'BlackFiles':[],
        'line_length':0,'mark':0}
    if any(_canonical_json(config.get(k))!=_canonical_json(v) for k,v in overrides.items()):_fail(detail='unsafe config')
    pd=report['program_data']
    if not isinstance(pd,dict) or set(pd)!={'path','size','sha256','rows'} or pd['path']!='program-data.json':_fail(detail='ProgramData artifact')
    path=pipeline/'program-data.json'
    program_raw=_bounded(path,MAX_REPORT)
    if type(pd['size']) is not int or pd['size']!=len(program_raw) or hashlib.sha256(program_raw).hexdigest()!=pd['sha256']:_fail(detail='ProgramData hash')
    data=_strict_loads(program_raw.decode('utf-8-sig'))
    if not isinstance(data,dict) or set(data)!={'schema_version','rows'} or type(data['schema_version']) is not int or data['schema_version']!=1:_fail(detail='ProgramData format')
    if type(pd['rows']) is not int or pd['rows']!=len(data['rows']):_fail(detail='ProgramData count')
    if _canonical_json(report['source_duplicates'])!=_canonical_json(source_duplicates):_fail(detail='duplicate-key inventory')
    discovery_only={r['path'] for r in source_duplicates}
    proven=_program_proofs(data['rows'],documents,discovery_only)
    rounds=report['rounds']
    if not isinstance(rounds,list) or not 1<=len(rounds)<=256:_fail(detail='round count')
    wanted={(rel,c.pointer):c for rel,changes in requested.items() for c in changes}
    baseline={r['path']:r for r in source_rows}
    cumulative=copy.deepcopy(documents);seen=set();expected_files={'program-data.json','project-report.json'}
    expected_files.update('input/'+r['path'] for r in source_rows)
    outputs={};locators={rel:[] for rel in requested};previous_root=str(pipeline/'input')
    for index,stage in enumerate(rounds):
        if not isinstance(stage,dict) or set(stage)!={'root','input_root','changes','files'}:_fail(detail='round fields')
        relroot=stage['root']
        if relroot!=f'rounds/{index:04d}' or not _ROUND.fullmatch(relroot) or stage['input_root']!=previous_root:
            _fail(detail='round root')
        stage_root=safe_join(pipeline,relroot,must_exist=True);previous_root=str(stage_root)
        if not isinstance(stage['changes'],list):_fail(detail='round changes')
        used=set()
        for change in stage['changes']:
            if not isinstance(change,dict) or set(change)!={'relative_path','file','pointer','source_text','text','address','code','labels'}:
                _fail(detail='round change')
            rel=change['relative_path'];pointer=change['pointer'];key=(rel,pointer)
            expected=wanted.get(key)
            if expected is None or key in seen or change['source_text']!=expected.source_text or change['text']!=expected.text:
                _fail('BACKEND_UNAPPROVED_DIFF','round request')
            if change['file'].replace('\\','/')!=rel.removeprefix('data/'):_fail(detail='round table owner')
            identity=(rel,expected.source_text)
            if identity in used:_fail(detail='duplicate original in round')
            used.add(identity);seen.add(key)
            proof=(rel,pointer,expected.source_text,change['address'],change['code'])
            if proven.get(proof)!=1:_fail('BACKEND_LOCATOR_UNSUPPORTED')
            _assign_leaf(cumulative[rel],expected.tokens,expected.text)
            locators.setdefault(rel,[]).append(dict(change,round=index))
        if not isinstance(stage['files'],list):_fail(detail='round manifest')
        manifest={}
        for record in stage['files']:
            if not isinstance(record,dict) or set(record)!={'path','size','sha256','source_sha256','byte_changed','semantic_changed'}:
                _fail(detail='round file')
            rel=record['path']
            if rel in manifest or rel not in documents:_fail(detail='round output path')
            path=safe_join(stage_root,rel,must_exist=True);raw=_bounded(path,MAX_JSON)
            if type(record['size']) is not int or len(raw)!=record['size'] or hashlib.sha256(raw).hexdigest()!=record['sha256']:
                _fail(detail='round output hash')
            original=baseline[rel]
            if record['source_sha256']!=original['sha256']:_fail(detail='round source hash')
            actual=_json(raw)
            if _canonical_json(actual)!=_canonical_json(cumulative[rel]):_fail('BACKEND_UNAPPROVED_DIFF')
            original_raw=_bounded(pipeline/'input'/rel,MAX_JSON)
            if raw.startswith(b'\xef\xbb\xbf')!=original_raw.startswith(b'\xef\xbb\xbf'):_fail('BACKEND_UNAPPROVED_DIFF','BOM')
            if (type(record['byte_changed']) is not bool or record['byte_changed']!=(record['sha256']!=original['sha256']) or
                type(record['semantic_changed']) is not bool or record['semantic_changed']!=(_canonical_json(actual)!=_canonical_json(documents[rel]))):
                _fail(detail='round diff summary')
            expected_files.add(relroot+'/'+rel);manifest[rel]=path
        if set(manifest)!=set(documents):_fail('BACKEND_SIDE_EFFECT','round file set')
        outputs=manifest
    if seen!=set(wanted):_fail('BACKEND_UNAPPROVED_DIFF','missing request')
    found,dirs=_tree(pipeline)
    if set(found)!=expected_files:_fail('BACKEND_SIDE_EFFECT','pipeline file set')
    expected_dirs={'input','cwd','rounds'}
    for rel in expected_files:
        expected_dirs.update(p.as_posix() for p in Path(rel).parents if p!=Path('.'))
    if dirs!=expected_dirs or list((pipeline/'cwd').iterdir()):_fail('BACKEND_SIDE_EFFECT','pipeline directories')
    _row_paths(pipeline/'input',source_rows)
    return report,outputs,locators


def rewrite_project(files,changes,work_root,backend_root,*,check=None):
    """Clone a full manifest and run actual Stev directory IO in one owned worker.

    ``files`` maps safe game-relative paths to immutable bytes or existing source
    file paths. ``changes`` contains only native-approved whole JSON leaves.
    Partial results stay private on every failure; this method publishes no game.
    """
    check=check or (lambda:None)
    if not callable(check):_fail('BACKEND_CONTROL_INVALID')
    if not isinstance(changes,dict):_fail('BACKEND_CHANGES_INVALID')
    work=bridge._validate_work_root(work_root);case=bridge._create_case_dir(work)
    pipeline=case/'pipeline';pipeline.mkdir();game=pipeline/'input';game.mkdir();cwd=pipeline/'cwd';cwd.mkdir()
    root=bridge._validate_backend_root(backend_root,'stev');upstream=_upstream(root)
    rows=_clone(files,game,check);_row_paths(game,rows)
    documents={};source_duplicates=[]
    for rel in sorted(files):
        if not (rel.startswith('data/') and rel.endswith('.json')):continue
        document,duplicates=parse_source_json(_bounded(game/rel,MAX_JSON),writable=bool(changes.get(rel)))
        documents[rel]=document
        if duplicates:source_duplicates.append({'path':rel,'keys':duplicates})
    if not documents or set(changes)-set(documents):_fail('BACKEND_DOCUMENT_UNSUPPORTED')
    requested={}
    for rel,items in changes.items():
        expected=copy.deepcopy(documents[rel]);requested[rel]=_normalize_changes(items,documents[rel],expected)
        if any(c.text=='' for c in requested[rel]):_fail('BACKEND_EMPTY_TRANSLATION_UNSUPPORTED')
    payload={'backend':'stev','operation':'stev_project','backend_root':str(root),'case_root':str(pipeline),
        'source_manifest':rows,'upstream_files':upstream,'changes':changes}
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(encoded)>bridge.MAX_IO_BYTES:_fail('BACKEND_REQUEST_TOO_LARGE')
    atomic_write(case/'request.json',encoded);check()
    completed=_run_project_worker(payload,cwd)
    atomic_write(case/'result.json',completed.stdout)
    result=bridge._decode_result(completed.stdout,completed,'stev');check()
    report,outputs,locators=_validate(pipeline,result,rows,upstream,documents,requested,source_duplicates)
    if _upstream(root)!=upstream:_fail('BACKEND_SOURCE_CHANGED')
    # The SDK can never write parent-owned success artifacts.
    sidecar=case/'sidecar.json';raw=json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8')
    check();atomic_write(sidecar,raw)
    sidecars={}
    for rel in sorted(outputs):
        check()
        proof={'backend':'stev','relative_path':rel,'source_sha256':next(r['sha256'] for r in rows if r['path']==rel),
            'discovery_only':any(r['path']==rel for r in source_duplicates),
            'bom':(game/rel).read_bytes().startswith(b'\xef\xbb\xbf'),
            'requested_pointers':[c.pointer for c in requested.get(rel,[])],
            'locators':locators.get(rel,[]),'pipeline':{'entrypoint':report['entrypoint'],
                'project_sidecar_sha256':hashlib.sha256(raw).hexdigest(),'project_sidecar_path':str(sidecar),
                'game_root':str(game),'config_sha256':report['config_sha256'],'rounds':report['rounds'],
                'source_duplicates':source_duplicates}}
        path=safe_join(case,'sidecars/'+rel+'.json');atomic_write(path,json.dumps(proof,ensure_ascii=False).encode('utf-8'))
        sidecars[rel]=str(path)
    check()
    return {'output_paths':{r:str(p) for r,p in outputs.items()},'sidecars':sidecars,'sidecar_path':str(sidecar),
        'discovery_only_paths':[r['path'] for r in source_duplicates],
        'capabilities':{'game_directory_read':True,'program_data_bridge':True,'memory_only':False,
            'third_party_write_api':True,'auto_plugins_loaded':False,'file_writes':True,'gui_launched':False}}
