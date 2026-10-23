"""Explicit per-file selection pinned to inspected code and main-entry config."""
import hashlib
import json
import os
from pathlib import Path

from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import rewrite_document,rewrite_js_document
from ModuleFolders.Infrastructure.GameAdapters.JsWorker.JsBridge import compile_js_changes,audit_js_changes
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import compile_json_changes
from .BackendCandidateService import generate_candidate
from .BuildService import file_hash
from .PathGuard import safe_join
from .ProjectLock import ProjectLock
from ModuleFolders.Infrastructure.GameAdapters.Capabilities import route_support
from ModuleFolders.Domain.GameProject.Models import Issue


def route_issues(routes,known_paths):
    """Validate the frozen single-writer route map before touching any output."""
    if not isinstance(routes,dict):
        return (Issue('BACKEND_ROUTE_INVALID','error','Backend route map must be an object'),)
    known=set(known_paths);seen=set();issues=[]
    for rel,route in routes.items():
        normalized=rel.replace('\\','/').casefold() if isinstance(rel,str) else ''
        if normalized in seen:
            issues.append(Issue('BACKEND_ROUTE_CONFLICT','error','Multiple whole-file writers target one file',path=rel))
            continue
        seen.add(normalized)
        invalid=not isinstance(route,dict) or rel not in known
        backend=route.get('backend') if isinstance(route,dict) else None
        if not isinstance(backend,str) or backend not in {'stev','rpgmtl','sextractor'}:
            invalid=True
        elif route_support(backend,rel)['status']=='unsupported':
            invalid=True
        if not invalid:
            root=route.get('backend_root');fingerprint=route.get('fingerprint')
            invalid=(not isinstance(root,str) or not Path(root).is_absolute() or
                not isinstance(fingerprint,dict) or not isinstance(fingerprint.get('files'),dict) or
                not fingerprint.get('files') or not isinstance(fingerprint.get('digest'),str) or
                len(fingerprint['digest'])!=64 or any(c not in '0123456789abcdef' for c in fingerprint['digest']))
        if invalid:
            issues.append(Issue('BACKEND_ROUTE_INVALID','error','Unsupported or malformed file backend route',path=rel))
    return tuple(issues)


def fingerprint(root):
    root=Path(root).absolute()
    is_stev=(root/'jtpp.py').is_file()
    files={}
    for folder,directories,names in os.walk(root,followlinks=False):
        directories[:]=sorted(name for name in directories if name not in {'.git','__pycache__','.venv','node_modules'})
        for directory in directories:
            safe_join(root,(Path(folder)/directory).relative_to(root).as_posix(),must_exist=True)
        for name in sorted(names):
            rel=(Path(folder)/name).relative_to(root).as_posix()
            # Directory writers use captured configuration, not only Python.
            if not (name.endswith('.py') or rel.casefold()=='src/engine.ini' or
                    (is_stev and rel.casefold()=='config.yaml')):continue
            path=safe_join(root,rel,must_exist=True)
            if path.stat().st_size>16*1024*1024:raise ValueError('BACKEND_SOURCE_FILE_TOO_LARGE')
            files[rel]=file_hash(path)
            if len(files)>5000:raise ValueError('BACKEND_SOURCE_TREE_TOO_LARGE')
    if not files:raise ValueError('BACKEND_SOURCE_NOT_FOUND')
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'digest':digest,'files':files}


def configure_route(store,relative_path,backend,backend_root=None,*,on_job=None):
    support=route_support(backend,relative_path)
    if support['status']=='unsupported':raise ValueError('BACKEND_FILE_UNSUPPORTED: '+support['reason'])
    if not isinstance(relative_path,str) or not relative_path.casefold().endswith(('.json','.js')) or not any(
        r['relative_path']==relative_path for r in store.files()):raise ValueError('BACKEND_DOCUMENT_UNSUPPORTED')
    if backend=='native':
        with ProjectLock(store.root):
            routes=dict(store.metadata().get('backend_routes',{}));routes.pop(relative_path,None)
            store.update_metadata({'backend_routes':routes})
        return {'relative_path':relative_path,'backend':'native'}
    if backend_root is None:raise ValueError('BACKEND_ROOT_REQUIRED')
    root=Path(backend_root).absolute()
    if backend=='stev':
        try:config=safe_join(root,'config.yaml',must_exist=True)
        except ValueError:raise ValueError('BACKEND_DEPENDENCY_MISSING: config.yaml') from None
        if not config.is_file():raise ValueError('BACKEND_DEPENDENCY_MISSING: config.yaml')
    before=fingerprint(root)
    proof=generate_candidate(store,backend,root,relative_path,on_job=on_job)
    if not proof['changed_occurrences']:raise ValueError('BACKEND_ROUTE_REQUIRES_TRANSLATED_UNIT')
    after=fingerprint(root)
    if before!=after:raise ValueError('BACKEND_SOURCE_CHANGED')
    with ProjectLock(store.root):
        meta=store.metadata()
        if meta['content_revision']!=proof['content_revision']:raise ValueError('BACKEND_ROUTE_INPUT_CHANGED')
        routes=dict(meta.get('backend_routes',{}))
        routes[relative_path]={'backend':backend,'backend_root':str(root),'fingerprint':before}
        store.update_metadata({'backend_routes':routes})
    return {'relative_path':relative_path,'backend':backend,'fingerprint':before['digest'],
            'proof':proof,'requires_exact_output_comparison':True}


def routed_write(project_root,relative_path,original,replacements,expected,route):
    support=route_support(route['backend'],relative_path)
    if support['status']!='candidate_required':raise ValueError('BACKEND_FILE_UNSUPPORTED: '+support['reason'])
    root=Path(route['backend_root'])
    if fingerprint(root)!=route['fingerprint']:raise ValueError('BACKEND_SOURCE_CHANGED')
    is_js=relative_path.casefold().endswith('.js')
    changes=(compile_js_changes if is_js else compile_json_changes)(original,replacements)
    result=(rewrite_js_document if is_js else rewrite_document)(route['backend'],relative_path,original,changes,
        safe_join(project_root,'work/backends'),root)
    output=result['output_bytes']
    canonical=lambda raw:json.dumps(json.loads(raw.decode('utf-8-sig')),sort_keys=True,
        ensure_ascii=False,separators=(',',':'),allow_nan=False)
    if is_js:audit_js_changes(original,output,changes)
    elif canonical(output)!=canonical(expected):raise ValueError('BACKEND_UNAPPROVED_DIFF')
    if fingerprint(root)!=route['fingerprint']:raise ValueError('BACKEND_SOURCE_CHANGED_DURING_BUILD')
    return output,{'id':route['backend'],'upstream_fingerprint':route['fingerprint']['digest'],
                   'sidecar_sha256':file_hash(result['sidecar_path'])}
