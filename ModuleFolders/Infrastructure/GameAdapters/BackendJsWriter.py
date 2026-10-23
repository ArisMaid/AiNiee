"""Real RPGMTL Javascript.read/write bridge, restricted to proven literal spans.

Runs only inside BackendWorker. Acorn validation belongs to the parent before
candidate publication; no original game directory or JS execution is needed.
"""
import codecs
import hashlib
import importlib
import os
import sys
from types import SimpleNamespace

from .BackendWriters import (WriterError,_run_upstream,_drop_foreign_modules,
    _validate_backend_root,MAX_SOURCE_BYTES,MAX_OUTPUT_BYTES)
from .RpgmtlJsMapping import TrackedJs,map_js_groups


def write_js_document(backend,backend_root,relative_path,source,changes):
    if backend!='rpgmtl':raise WriterError('BACKEND_FILE_UNSUPPORTED')
    from .Capabilities import route_support
    if route_support(backend,relative_path)['status']!='candidate_required' or not relative_path.casefold().endswith('.js'):
        raise WriterError('BACKEND_PATH_INVALID')
    root=_validate_backend_root(backend_root)
    if not os.path.isfile(os.path.join(root,'plugins','javascript.py')):
        raise WriterError('BACKEND_UPSTREAM_MISSING','plugins/javascript.py')
    if not isinstance(source,bytes):raise WriterError('BACKEND_SOURCE_INVALID')
    if len(source)>MAX_SOURCE_BYTES:raise WriterError('BACKEND_SOURCE_TOO_LARGE')
    try:source_text=source.decode('utf-8-sig')
    except UnicodeError:raise WriterError('BACKEND_SOURCE_ENCODING_INVALID') from None
    bom=3 if source.startswith(codecs.BOM_UTF8) else 0
    upstream=source[bom:]
    if changes==[]:
        return {'output_bytes':source,'sidecar':{'backend':backend,'relative_path':relative_path,
            'source_sha256':hashlib.sha256(source).hexdigest(),'bom':bool(bom),
            'requested_spans':[],'locators':[],'upstream_modified':False},
            'capabilities':{'memory_only':True,'third_party_write_api':False,
                'isolated_process_required':True,'approved_display_text':False,
                'positional_provenance':True,'parent_ast_audit_required':True}}
    _drop_foreign_modules(root,('plugins','plugins.javascript'))
    if root not in sys.path:sys.path.insert(0,root)
    module=_run_upstream(importlib.import_module,'plugins.javascript')
    plugin=_run_upstream(module.Javascript)
    plugin.set_settings({})
    owner=SimpleNamespace(CHILDREN_FILE_ID='::',strings={})
    plugin.owner=owner
    tracked=TrackedJs(source_text)
    # Bind only this instance during read. Restore before calling the real
    # writer so it reparses the original bytes through its normal decoder.
    decode=plugin.decode
    try:
        plugin.decode=lambda content:tracked
        groups=_run_upstream(plugin.read,relative_path,upstream)
    finally:plugin.decode=decode
    try:mapped=map_js_groups(tracked,relative_path,groups,changes,bom=bom)
    except ValueError:raise WriterError('BACKEND_LOCATOR_UNSUPPORTED','JS positional proof rejected') from None
    owner.strings['ainiee']=mapped['project_strings']
    output,modified=_run_upstream(plugin.write,'ainiee',relative_path,upstream)
    if not isinstance(output,bytes):raise WriterError('BACKEND_UPSTREAM_FAILURE','Javascript.write output type')
    if bom:output=codecs.BOM_UTF8+output
    if len(output)>MAX_OUTPUT_BYTES:raise WriterError('BACKEND_OUTPUT_TOO_LARGE')
    return {'output_bytes':output,'sidecar':{'backend':backend,'relative_path':relative_path,
        'source_sha256':hashlib.sha256(source).hexdigest(),'bom':bool(bom),
        'requested_spans':[[row['start'],row['end']] for row in changes],
        'locators':mapped['found'],'upstream_modified':bool(modified)},
        'capabilities':{'memory_only':True,'third_party_write_api':True,
            'isolated_process_required':True,'approved_display_text':False,
            'positional_provenance':True,'parent_ast_audit_required':True}}
