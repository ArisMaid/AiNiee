"""RPG Maker MV/MZ game root detection (contract v1)."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

from ModuleFolders.Service.GameProject.PathGuard import PathViolation, safe_join

__all__ = ['GameDetectionError', 'detect_game']

_MZ_CORE = 'js/rmmz_core.js'
_MV_CORE = 'js/rpg_core.js'
_STANDARD_DATABASES = ('Actors','Animations','Armors','Classes','CommonEvents','Enemies',
    'Items','MapInfos','Skills','States','System','Tilesets','Troops','Weapons')
_VERSION_PATTERNS = (
    re.compile(r'RPGMAKER_VERSION\s*=\s*[\'"]([^\'"]+)[\'"]'),
    re.compile(r'\bv(\d+(?:\.\d+)+)'),
)


class GameDetectionError(ValueError):
    """Raised when no RPG Maker MV/MZ game root can be identified at all."""


def detect_game(source) -> dict:
    """Return detection metadata for an MV/MZ game directory or launcher EXE.

    ``root`` is the directory holding ``data``/``js``/``index.html`` (the
    ``www`` directory for the classic MV layout), so ``data_dir`` and ``js_dir``
    are always relative to it.  An ambiguous input (both ``data`` and
    ``www/data`` are complete games) raises :class:`ValueError`.
    """

    base = _source_directory(source)
    found = []
    for candidate in (base, base / 'www'):
        info = _describe(candidate)
        if info is not None:
            found.append((candidate, info))
    if not found:
        raise GameDetectionError(f'no RPG Maker MV/MZ game found at {source!r}')
    if len(found) > 1:
        roots = ', '.join(str(root) for root, _ in found)
        raise ValueError(f'ambiguous RPG Maker game roots: {roots}')
    return found[0][1]


def _source_directory(source) -> Path:
    try:
        text = os.fspath(source)
    except TypeError as error:
        raise GameDetectionError(
            f'source must be a path, got {type(source).__name__}'
        ) from error
    if isinstance(text, bytes):
        raise GameDetectionError('source must be a string path, not bytes')
    if text == '':
        raise GameDetectionError('source must not be empty')
    path = Path(os.path.abspath(text))
    if path.suffix.lower() == '.exe':
        return path.parent
    try:
        is_file = path.is_file()
    except OSError:
        is_file = False
    if is_file:
        raise GameDetectionError(f'source must be a game directory: {text!r}')
    return path


def _describe(base: Path):
    if not _is_file(base, 'data/System.json'):
        return None
    if _is_file(base, _MZ_CORE):
        engine = 'rpgmaker-mz'
        core_name = _MZ_CORE
    elif _is_file(base, _MV_CORE):
        engine = 'rpgmaker-mv'
        core_name = _MV_CORE
    else:
        return None
    if not (_is_file(base, 'index.html') or _is_file(base, 'package.json')):
        return None
    system = _read_json(base, 'data/System.json')
    if not isinstance(system, Mapping):
        return None
    core_text = _read_text(base, core_name) or ''
    declared = re.search(r'RPGMAKER_NAME\s*=\s*[\'"](MV|MZ)[\'"]',core_text)
    if declared and declared.group(1) != ('MZ' if engine=='rpgmaker-mz' else 'MV'):
        return None
    return {
        'root': str(base),
        'data_dir': 'data',
        'js_dir': 'js',
        'engine': engine,
        'engine_version': _read_version(base, core_name),
        'locale': _text(system.get('locale')),
        'game_title': _text(system.get('gameTitle')),
        'game_id': _game_id(system),
        'detection_evidence': _root_evidence(base,core_name,system,core_text),
    }


def _root_evidence(base,core_name,system,core_text):
    """Record static observations; absent/runtime-only evidence stays explicit."""
    index = _read_text(base,'index.html')
    scripts=[];external=0
    if index is not None:
        for value in re.findall(r'<script\b[^>]*\bsrc\s*=\s*[\'"]([^\'"]+)[\'"]',index,re.I):
            relative=value.split('?',1)[0].split('#',1)[0].replace('\\','/')
            while relative.startswith('./'):relative=relative[2:]
            try:safe_join(base,relative)
            except PathViolation:
                external+=1;continue
            scripts.append({'path':relative,'exists':_is_file(base,relative)})
    package=_read_json(base,'package.json')
    main=package.get('main') if isinstance(package,Mapping) else None
    main_status='not_declared'
    if isinstance(main,str) and main:
        relative=main.split('?',1)[0].split('#',1)[0]
        while relative.startswith('./'):relative=relative[2:]
        try:main_status='exists' if _is_file(base,relative) else 'missing_or_outside_root'
        except (ValueError,OSError):main_status='unavailable'
    declared_engine=re.search(r'RPGMAKER_NAME\s*=\s*[\'"](MV|MZ)[\'"]',core_text)
    main_js=_read_text(base,'js/main.js') if any(r['path']=='js/main.js' for r in scripts) else None
    core_reference=('index.html script src' if any(r['path']==core_name for r in scripts)
        else 'js/main.js text reference' if main_js is not None and core_name in main_js else 'not_confirmed')
    return {'status':'recorded','scope':'Static files only; game executables were not run',
        'core_script':core_name,'declared_engine':declared_engine.group(1) if declared_engine else None,
        'index_html':'read' if index is not None else 'absent_or_unreadable',
        'index_scripts':scripts,'external_or_invalid_script_references':external,
        'core_reference':core_reference,
        'package_json':'object' if isinstance(package,Mapping) else 'absent_or_invalid',
        'package_main':main_status,
        'missing_standard_files':[f'data/{name}.json' for name in _STANDARD_DATABASES if not _is_file(base,f'data/{name}.json')],
        'resource_encryption':{'source':'data/System.json',
            'images':system.get('hasEncryptedImages') if type(system.get('hasEncryptedImages')) is bool else None,
            'audio':system.get('hasEncryptedAudio') if type(system.get('hasEncryptedAudio')) is bool else None},
        'nwjs':{'version':None,'status':'not_measured_during_detection',
            'files_present':[name for name in ('Game.exe','nw.exe','nw.dll','node.dll') if _is_file(base,name)],
            'next_step':'Record process.versions.nw during an authorized output-copy runtime check; do not infer it from package.json game version'}}


def _read_text(base,relative):
    try:return safe_join(base,relative,must_exist=True).read_bytes().decode('utf-8-sig')
    except (PathViolation,OSError,UnicodeError):return None


def _is_file(base: Path, relative: str) -> bool:
    try:
        target = safe_join(base, relative)
    except (PathViolation, OSError):
        return False
    try:
        return target.is_file()
    except OSError:
        return False


def _read_json(base: Path, relative: str):
    try:
        target = safe_join(base, relative, must_exist=True)
        payload = target.read_bytes()
    except (PathViolation, OSError):
        return None
    try:
        return json.loads(payload.decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError):
        return None


def _read_version(base: Path, relative: str) -> str:
    try:
        target = safe_join(base, relative, must_exist=True)
        text = target.read_text(encoding='utf-8', errors='ignore')
    except (PathViolation, OSError, UnicodeDecodeError):
        return ''
    for pattern in _VERSION_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ''


def _game_id(system: Mapping) -> str:
    advanced = system.get('advanced')
    if not isinstance(advanced, Mapping):
        return ''
    value = advanced.get('gameId')
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return ''
    text = str(value).strip()
    return text


def _text(value) -> str:
    return value if isinstance(value, str) else ''
