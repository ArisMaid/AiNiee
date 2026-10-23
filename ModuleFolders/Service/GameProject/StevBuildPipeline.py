"""Prepare one genuine directory candidate per frozen Stev tool/root group."""
from collections import defaultdict
from pathlib import Path

from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import compile_json_changes,patch_json
from ModuleFolders.Infrastructure.GameAdapters.StevProjectBridge import rewrite_project,_json
from ModuleFolders.Infrastructure.GameAdapters.BackendWriters import _canonical_json
from .PathGuard import safe_join


def prepare_stev_routes(project_root,source_root,files,changes,routes,check):
    """Return only requested file candidates, with the full game audited first.

    Configured non-Stev routes and native permissions remain unchanged. All
    declared input files (including assets) are present in the SDK's work clone.
    No candidate is installed into BuildService staging by this preparation.
    """
    from .BackendRoutes import fingerprint
    from .BuildService import file_hash
    groups=defaultdict(dict)
    for rel,route in routes.items():
        if route['backend']!='stev' or rel not in changes:continue
        if not rel.startswith('data/') or not rel.endswith('.json') or {o.adapter_id for o,_ in changes[rel]}!={'rpgmaker-native'}:
            raise ValueError('BACKEND_DOCUMENT_UNSUPPORTED')
        key=(route['backend_root'],route['fingerprint']['digest'])
        groups[key][rel]=route
    if not groups:return {}
    inputs={}
    for record in files:
        check();rel=record['relative_path']
        original=safe_join(source_root,rel,must_exist=True)
        if file_hash(original)!=record['sha256']:raise ValueError('SOURCE_CHANGED')
        captured=record.get('captured_path')
        path=safe_join(project_root,captured,must_exist=True) if captured else original
        if file_hash(path)!=record['sha256']:raise ValueError('SNAPSHOT_HASH_MISMATCH')
        inputs[rel]=path
    prepared={}
    for (root,_),members in groups.items():
        check();reference=next(iter(members.values()))['fingerprint']
        if fingerprint(root)!=reference:raise ValueError('BACKEND_SOURCE_CHANGED')
        requests={rel:compile_json_changes(inputs[rel].read_bytes(),changes[rel]) for rel in members}
        result=rewrite_project(inputs,requests,safe_join(project_root,'work/backends'),Path(root),check=check)
        for rel in members:
            check();path=Path(result['output_paths'][rel]);actual=path.read_bytes()
            expected=patch_json(inputs[rel].read_bytes(),changes[rel])
            if _canonical_json(_json(actual))!=_canonical_json(_json(expected)):raise ValueError('BACKEND_UNAPPROVED_DIFF')
            prepared[rel]={'output_path':str(path),'output_sha256':file_hash(path),
                'writer':{'id':'stev','upstream_fingerprint':reference['digest'],
                    'sidecar_sha256':file_hash(Path(result['sidecars'][rel])),
                    'project_sidecar_sha256':file_hash(Path(result['sidecar_path'])),
                    'project_source_files':len(inputs),'entrypoint':'Jr_Tpp.ReadGame -> Jr_Tpp.InjectGame'}}
        if fingerprint(root)!=reference:raise ValueError('BACKEND_SOURCE_CHANGED_DURING_BUILD')
    return prepared
