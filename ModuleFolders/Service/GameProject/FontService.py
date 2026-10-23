"""Content-addressed, project-local font overrides for MZ output copies."""
from pathlib import Path
import hashlib
from .PathGuard import safe_join, atomic_write
from .FontInspector import inspect_font
from .TranslationCommitter import TranslationCommitter

ALIAS_SCRIPT='js/AiNieeFontAliases.js'
ALIAS_TAG=b'\n<script src="js/AiNieeFontAliases.js"></script>\n'


def alias_runtime_bytes(settings):
    if not settings.get('aliases'):return b''
    from .FontAliasRuntime import build_runtime
    return build_runtime(settings['aliases'],settings['output_file'])


def install_aliases(staging,manifest_files,settings,*,writer=None):
    write=atomic_write if writer is None else writer
    data=alias_runtime_bytes(settings)
    if not data:return {'enabled':False}
    target=safe_join(staging,ALIAS_SCRIPT)
    if target.exists():
        if target.read_bytes()!=data:raise ValueError('FONT_ALIAS_RUNTIME_CHANGED')
    else:write(target,data)
    html=safe_join(staging,'index.html',must_exist=True);before=html.read_bytes()
    if b'AiNieeFontAliases.js' in before:raise ValueError('FONT_ALIAS_SCRIPT_ALREADY_PRESENT')
    write(html,before+ALIAS_TAG,overwrite=True)
    row=next(r for r in manifest_files if r['path']=='index.html')
    row.update(output_sha256=hashlib.sha256(before+ALIAS_TAG).hexdigest(),changed=True,reason='configured_font_aliases')
    digest=hashlib.sha256(data).hexdigest()
    manifest_files.append({'path':ALIAS_SCRIPT,'original_sha256':None,'output_sha256':digest,
        'changed':True,'reason':'configured_font_aliases'})
    return {'enabled':True,'aliases':settings['aliases'],'script_sha256':digest,
        'runtime_validation':'not_run'}


def visible_unit_texts(store, *, include_source=False):
    policy=TranslationCommitter(store).policy
    texts=[]
    for unit in store.units():
        tr=store.translation(unit.unit_id) or {}
        valid=bool(tr.get('text')) and not tr.get('stale') and tr.get('source_hash')==unit.source_hash
        if not valid and not include_source:continue
        text=tr['text'] if valid else unit.source_text
        tokens,_=policy.scan(text)
        for token in reversed(tokens):text=text[:token.start]+text[token.end:]
        texts.append({'unit':unit,'text':text,'origin':'translation' if valid else 'source'})
    return texts


def visible_texts(store, *, include_source=False):
    return [row['text'] for row in visible_unit_texts(store,include_source=include_source)]


def inspect_project_font(store,path,*,include_source=False):
    """Static cmap report with exact unit links; does not infer runtime fallback."""
    from .FontInspector import _required_characters
    from ModuleFolders.Domain.GameProject.Models import Issue
    rows=visible_unit_texts(store,include_source=include_source)
    report=inspect_font(path,[row['text'] for row in rows]);missing=set(report['missing_characters'])
    issues=[];groups={}
    for origin in ('translation','source'):
        selected=[row for row in rows if row['origin']==origin]
        characters=_required_characters([row['text'] for row in selected])
        groups[origin]={'units':len(selected),'character_count':len(characters),
            'missing_characters':sorted(characters&missing),'missing_count':len(characters&missing)}
    for row in rows:
        absent=sorted(set(row['text'])&missing)
        if not absent:continue
        unit=row['unit'];paths=sorted({o.relative_path for o in unit.occurrences})
        issues.append(Issue('FONT_GLYPH_MISSING','error','Selected font cmap lacks characters in this unit',
            unit.unit_id,paths[0] if paths else '',dict(missing_characters=absent,text_origin=row['origin'],
                font_sha256=report['sha256'],paths=paths,measurement='static-cmap')).to_dict())
    settings=store.metadata().get('font_settings') or {}
    report.update(issues=issues,scope_counts=groups,translated_units_checked=groups['translation']['units'],
        source_units_checked=groups['source']['units'],
        coverage_scope='accepted translations plus retained source' if include_source else 'current accepted translations only',
        font_matches_configured_output=report['sha256']==settings['sha256'] if settings else None,
        dynamic_values_checked=False,fallback_validation='not_checked',runtime_validation='not_run')
    return report


def configure_font(store,path):
    if store.metadata()['engine']!='rpgmaker-mz':raise ValueError('FONT_OVERRIDE_REQUIRES_MZ')
    path=Path(path)
    if path.suffix.lower() not in {'.ttf','.otf','.woff','.woff2'}:raise ValueError('UNSUPPORTED_FONT_FORMAT')
    report=inspect_font(path,visible_texts(store,include_source=True))
    data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
    if digest!=report['sha256']:raise ValueError('FONT_CHANGED_DURING_INSPECTION')
    captured=f'fonts/{digest}{path.suffix.lower()}'
    target=safe_join(store.root,captured)
    if not target.exists():atomic_write(target,data)
    if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('FONT_SNAPSHOT_CHANGED')
    from ModuleFolders.Domain.GameProject.FontPolicy import normalize_aliases
    aliases=normalize_aliases(store.metadata().get('font_aliases',[]))
    settings={'captured_path':captured,'sha256':digest,'output_file':'AiNiee-Simplified'+path.suffix.lower(),
        'aliases':aliases}
    store.update_metadata({'font_settings':settings})
    return {'configured':True,'settings':settings,'coverage':report,'runtime_validation':'not_run'}
