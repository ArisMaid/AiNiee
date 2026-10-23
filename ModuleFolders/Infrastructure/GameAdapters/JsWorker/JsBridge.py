"""Parse JavaScript without running it; patch only approved literal nodes."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from ModuleFolders.Domain.GameProject.Models import Issue, Occurrence, TranslationUnit, hash_text
from ModuleFolders.Domain.GameProject.AdapterProtocol import ExtractionResult
from ModuleFolders.Service.GameProject.PathGuard import safe_join
from ModuleFolders.Infrastructure.Platform.WorkerProtocol import run_json_worker
from ModuleFolders.Infrastructure.Platform.OwnedProcess import OutputLimitExceeded
from ModuleFolders.Domain.GameProject.EncodedJsonText import read_value,patch_values,text_affixes,source_span_body


def _call(payload):
    if payload.get('operation')=='audit':
        # JSON loses the distinction between Python 25.0 and 25. Enforce the
        # caller contract before serialization; Node separately validates its
        # numeric range and exact AST span.
        rows=payload.get('replacements')
        if not isinstance(rows,list) or any(not isinstance(row,dict) or
                type(row.get('start')) is not int or type(row.get('end')) is not int for row in rows):
            raise ValueError('JS_AUDIT_INVALID_RANGE')
    worker=Path(__file__).with_name('worker.cjs')
    root=worker.parents[4]
    runtime=Path(getattr(sys,'_MEIPASS',root))/'runtime'
    acorn=runtime/'js/node_modules/acorn'
    if not acorn.is_dir():
        layout=json.loads((root/'Tools/rpg_paths.json').read_text(encoding='utf-8'))
        workspace=Path(os.environ.get('RPG_WORKSPACE_ROOT',root.parent))
        acorn=workspace/layout['js']/'node_modules/acorn'
        if not acorn.is_dir():acorn=root/'.tools/js/node_modules/acorn'
    node=str(runtime/'node.exe') if (runtime/'node.exe').is_file() else shutil.which('node')
    if not node or not acorn.is_dir():raise ValueError('JS_BACKEND_NOT_READY: Node/locked Acorn dependency missing')
    # Node is invoked by its absolute executable path. Inherited NODE_OPTIONS
    # can preload arbitrary code before our parser; provider keys are unrelated
    # to this worker and must not cross the process boundary either.
    env={key:value for key,value in os.environ.items()
        if key.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP'} and value}
    env['RPG_ACORN_PATH']=str(acorn)
    encoded=json.dumps(payload,ensure_ascii=False).encode('utf-8')
    if len(encoded)>16*1024*1024:raise ValueError('JS_INPUT_TOO_LARGE')
    try:result=run_json_worker([node,str(worker)],payload,env=env,cwd=worker.parent,timeout=40)
    except OutputLimitExceeded as error:raise ValueError('JS_OUTPUT_TOO_LARGE') from error
    if len(result.stdout)>32*1024*1024:raise ValueError('JS_OUTPUT_TOO_LARGE')
    try:response=json.loads(result.stdout)
    except (ValueError,UnicodeError) as exc:raise ValueError('JS_PROTOCOL_ERROR') from exc
    if result.returncode or not response.get('ok'):raise ValueError(response.get('error','JS_WORKER_FAILED'))
    return response['value']


def extract_js_rules(root,rules,rule_cache=None):
    root=Path(root);units=[];issues=[];files=[]
    for index,rule in enumerate(rules):
        if rule.get('evidence_status')!='verified':
            issues.append(Issue('PROFILE_UNVERIFIED','warning','JS rule requires source audit',path=rule['file']))
            continue
        path=safe_join(root,rule['file'],must_exist=True);data=path.read_bytes()
        compute=lambda r=rule,b=data:_extract_rule_bytes(r,b)
        result=rule_cache(index,rule,data,compute) if rule_cache is not None else compute()
        if not isinstance(result,ExtractionResult):raise ValueError('JS_EXTRACTION_CACHE_INVALID')
        units.extend(result.units);issues.extend(result.issues);files.extend(result.files)
    return units,issues,files


def _extract_rule_bytes(rule,data):
    source=data.decode('utf-8-sig');bom=3 if data.startswith(b'\xef\xbb\xbf') else 0
    selector={key:rule[key] for key in ('scope_function','property_fields','static_text','literal_path') if key in rule}
    if 'source_spans' in rule:
        if hash_text(source)!=rule['source_sha256']:raise ValueError('JS_APPROVED_SOURCE_CHANGED')
        nodes=_call({'operation':'extract_spans','source':source,'spans':rule['source_spans']})
        for node in nodes:
            if hash_text(node['value'])!=node['expected_sha256']:raise ValueError('JS_APPROVED_TEXT_CHANGED')
            node['property_path']=['#source',node['id']]
            node['source_span_id']=node['id']
    else:
        nodes=_call({'operation':'extract','source':source,'object_path':rule['object_path'],**selector})
    if 'json_texts' in rule or 'json_scripts' in rule:
        expanded=[]
        for node in nodes:
            # RPG Maker's generated parameter strings use JSON-compatible JS quoting.
            literal=data[node['start']+bom:node['end']+bom].decode('utf-8')
            if json.loads(literal)!=node['value']:raise ValueError('JS_JSON_CONTAINER_LITERAL_UNSUPPORTED')
            for steps in rule.get('json_texts',[]):
                value,spec=read_value(node['value'],steps)
                expanded.append({**node,'value':value,'json_spec':spec})
            for entry in rule.get('json_scripts',[]):
                program,spec=read_value(node['value'],entry['json_steps'])
                if hash_text(program)!=entry['source_sha256']:raise ValueError('JS_JSON_SCRIPT_CHANGED')
                spans=_call({'operation':'extract_spans','source':program,'spans':entry['spans']})
                for span in spans:
                    if hash_text(span['value'])!=span['expected_sha256']:raise ValueError('JS_JSON_SCRIPT_TEXT_CHANGED')
                    address={k:span[k] for k in ('id','start','end','node_kind')}
                    address['source_sha256']=entry['source_sha256']
                    expanded.append({**node,'value':span['value'],'json_spec':spec,'script_span':address})
        nodes=expanded
    units=[]
    for n in nodes:
        display=source_span_body(n['value'],n['text_affixes'] if 'text_affixes' in n else None)
        if not display.strip():continue
        if 'text_affixes' in n and not n.get('source_span_id'):raise ValueError('JS_TEXT_AFFIXES_REQUIRE_SOURCE_SPAN')
        prefix=rule['file']+':'+rule['object_path']
        if rule.get('scope_function'):prefix+=':scope='+rule['scope_function']
        identity=prefix+':'+json.dumps(n['property_path'])
        if n.get('json_spec'):identity+=':json='+json.dumps(n['json_spec']['json_steps'])
        if n.get('script_span'):identity+=':script='+n['script_span']['id']
        uid=str(uuid.uuid5(uuid.NAMESPACE_URL,identity))
        loc={'start':n['start']+bom,'end':n['end']+bom,'expected':n['value'],
            'source_sha256':hashlib.sha256(data).hexdigest(),'object_path':rule['object_path'],
            'property_path':n['property_path'],**selector}
        if n.get('node_kind'):loc['node_kind']=n['node_kind']
        if n.get('source_span_id'):loc['source_span_id']=n['source_span_id']
        if 'text_affixes' in n:loc['text_affixes']=text_affixes(n['text_affixes'])
        if n.get('json_spec'):loc.update(n['json_spec'])
        if n.get('script_span'):loc['script_span']=n['script_span']
        occurrence=Occurrence(uid+':js',rule['file'],loc,hash_text(n['value']),adapter_id='js-literal')
        context={'object_path':rule['object_path'],'property_path':n['property_path'],**selector}
        if n.get('source_span_id'):context['source_span_id']=n['source_span_id']
        if 'text_affixes' in n:context['text_affixes']=loc['text_affixes']
        if n.get('json_spec'):context['json_steps']=n['json_spec']['json_steps']
        if n.get('script_span'):context['script_label']=n['script_span']['id']
        if rule.get('preserve_newlines'):context['value_constraints']={'preserve_newlines':True}
        units.append(TranslationUnit(uid,rule.get('kind','menu'),display,scene_id=rule.get('scene_id') or rule.get('scope_function') or rule['object_path'],
            context=context,occurrences=(occurrence,)))
    return ExtractionResult(units=tuple(units),files=({'relative_path':rule['file'],
        'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)},))


def patch_js(original,replacements):
    changes=compile_js_changes(original,replacements)
    bom=3 if original.startswith(b'\xef\xbb\xbf') else 0
    rows=[{key:row[key] for key in ('start','end','expected','text','node_kind') if key in row} for row in changes]
    for row in rows:row['start']-=bom;row['end']-=bom
    if all(row['expected']==row['text'] for row in changes):
        audit_js_changes(original,original,changes)
        return original
    patched=_call({'operation':'patch','source':original.decode('utf-8-sig'),'replacements':rows})
    return (b'\xef\xbb\xbf' if bom else b'')+patched.encode('utf-8')


def compile_js_changes(original,replacements):
    """Compile frozen approved occurrences; never infer a location from text."""
    digest=hashlib.sha256(original).hexdigest();bom=3 if original.startswith(b'\xef\xbb\xbf') else 0
    rows=[];groups={}
    for occurrence,text in replacements:
        loc=occurrence.locator
        if (occurrence.adapter_id!='js-literal' or loc.get('source_sha256')!=digest or
                not isinstance(loc.get('expected'),str) or hash_text(loc['expected'])!=occurrence.expected_value_hash):
            raise ValueError('JS_SOURCE_CHANGED')
        start,end=loc.get('start'),loc.get('end')
        if (type(start) is not int or type(end) is not int or not bom<=start<end<=len(original)
                or not isinstance(text,str)):
            raise ValueError('JS_LOCATOR_MISMATCH')
        literal=original[start:end].decode('utf-8');kind=loc.get('node_kind','literal')
        if 'text_affixes' in loc:
            if not loc.get('source_span_id') or any(k in loc for k in ('json_steps','static_text','scope_function','property_fields','literal_path','script_span')):
                raise ValueError('JS_TEXT_AFFIXES_REQUIRE_SOURCE_SPAN')
            source_span_body(loc['expected'],loc['text_affixes'])
            parts=text_affixes(loc['text_affixes']);text=parts['prefix']+text+parts['suffix']
        if 'json_steps' in loc:
            groups.setdefault((start,end),[]).append((loc,text))
            continue
        if kind not in ('literal','template-part') or (kind=='template-part' and
                loc.get('static_text') is not True and not loc.get('source_span_id')):
            raise ValueError('JS_LOCATOR_MISMATCH')
        if kind=='literal' and (len(literal)<2 or literal[0] not in "\"'" or literal[-1]!=literal[0]):
            raise ValueError('JS_LOCATOR_MISMATCH')
        rows.append({'start':start,'end':end,'expected':loc['expected'],'source_literal':literal,'text':text})
        if kind=='template-part':rows[-1]['node_kind']=kind
    for (start,end),edits in groups.items():
        literal=original[start:end].decode('utf-8')
        try:outer=json.loads(literal)
        except ValueError as error:raise ValueError('JS_JSON_CONTAINER_LITERAL_UNSUPPORTED') from error
        if not isinstance(outer,str):raise ValueError('JS_JSON_CONTAINER_NOT_STRING')
        rows.append(dict(start=start,end=end,expected=outer,source_literal=literal,text=patch_values(outer,edits,_patch_encoded_script)))
    ordered=sorted((r['start'],r['end']) for r in rows)
    if any(left[1]>right[0] for left,right in zip(ordered,ordered[1:])):
        raise ValueError('JS_LOCATOR_MISMATCH')
    return rows


def _patch_encoded_script(program,edits):
    raw=program.encode('utf-8');pairs=[]
    for locator,text in edits:
        span=locator['script_span']
        inner={k:span[k] for k in ('start','end','node_kind','source_sha256')}
        inner.update(expected=locator['expected'],static_text=True)
        pairs.append((Occurrence(span['id'],'embedded.js',inner,hash_text(locator['expected']),adapter_id='js-literal'),text))
    changes=compile_js_changes(raw,pairs);output=patch_js(raw,pairs)
    audit_js_changes(raw,output,changes)
    return output.decode('utf-8')


def audit_js_changes(original,output,changes):
    """Independently prove logical values, AST and every unapproved byte."""
    bom=3 if original.startswith(b'\xef\xbb\xbf') else 0
    if bool(bom)!=output.startswith(b'\xef\xbb\xbf'):raise ValueError('JS_AUDIT_BOM_CHANGED')
    rows=[{key:row[key] for key in ('start','end','expected','text','node_kind') if key in row} for row in changes]
    for row in rows:row['start']-=bom;row['end']-=bom
    return _call({'operation':'audit','source':original.decode('utf-8-sig'),
        'output':output.decode('utf-8-sig'),'replacements':rows})
