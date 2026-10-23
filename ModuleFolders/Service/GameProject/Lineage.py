"""Pure explicit-lineage identity utility for confirmed game migrations.

Records only an explicit user assertion; never infers identity from titles and
never relaxes migration location/source/token/revision guards.
"""

import re
from collections.abc import Mapping

_CONFIRMATION_REQUIRED = 'MIGRATION_LINEAGE_CONFIRMATION_REQUIRED'
_SAME_PROJECT = 'MIGRATION_SAME_PROJECT'
_PROJECT_MISMATCH = 'MIGRATION_PROJECT_MISMATCH'
_LINEAGE_UNBOUND = 'MIGRATION_LINEAGE_UNBOUND'

_MANIFEST_HASH = re.compile(r'[0-9a-f]{64}')
_SIGNED_DIGITS = re.compile(r'[+-]?[0-9]+')
_SUPPORTED_ENGINES = frozenset(('rpgmaker-mv', 'rpgmaker-mz'))


def game_identity(value):
    """Return (canonical, reported) or two empty strings when unknown."""
    if isinstance(value, bool) or value is None:
        return ('', '')
    if isinstance(value, int):
        if value <= 0:
            return ('', '')
        try:
            return (str(value), value)
        except ValueError:
            return ('', '')
    if not isinstance(value, str):
        return ('', '')
    text = value.strip()
    if not text:
        return ('', '')
    if _SIGNED_DIGITS.fullmatch(text):
        try:
            number = int(text)
            return (str(number), text) if number > 0 else ('', '')
        except ValueError:
            return ('', '')
    return (text, text)


def _text(metadata, key):
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) else ''


def _required_text(metadata, key, code):
    value = _text(metadata, key)
    if not value:
        raise ValueError(f'{code}: missing or blank {key}')
    return value


def _manifest_hash(metadata):
    value = metadata.get('source_manifest_hash')
    if not isinstance(value, str) or not _MANIFEST_HASH.fullmatch(value):
        raise ValueError(f'{_LINEAGE_UNBOUND}: invalid source_manifest_hash')
    return value


def _language(metadata):
    value = metadata.get('target_language')
    if value is None:
        return 'zh-CN'
    if isinstance(value, str):
        return value.strip() or 'zh-CN'
    return ''


def build_confirmation(old_metadata, new_metadata, confirmed=False):
    """Validate explicit bindings and return a fresh JSON-native record."""
    if confirmed is not True:
        raise ValueError(f'{_CONFIRMATION_REQUIRED}: explicit confirmation required')
    if not isinstance(old_metadata, Mapping) or not isinstance(new_metadata, Mapping):
        raise ValueError(f'{_LINEAGE_UNBOUND}: metadata mappings required')

    old_project_id = _required_text(old_metadata, 'project_id', _LINEAGE_UNBOUND)
    new_project_id = _required_text(new_metadata, 'project_id', _LINEAGE_UNBOUND)
    if old_project_id == new_project_id:
        raise ValueError(f'{_SAME_PROJECT}: distinct project ids required')

    old_engine = _required_text(old_metadata, 'engine', _LINEAGE_UNBOUND)
    new_engine = _required_text(new_metadata, 'engine', _LINEAGE_UNBOUND)
    if old_engine not in _SUPPORTED_ENGINES or new_engine not in _SUPPORTED_ENGINES:
        raise ValueError(f'{_LINEAGE_UNBOUND}: unsupported engine')
    if old_engine != new_engine:
        raise ValueError(f'{_PROJECT_MISMATCH}: engine mismatch')

    if _language(old_metadata) != 'zh-CN' or _language(new_metadata) != 'zh-CN':
        raise ValueError(f'{_PROJECT_MISMATCH}: target language mismatch')

    old_manifest_hash = _manifest_hash(old_metadata)
    new_manifest_hash = _manifest_hash(new_metadata)

    old_game_id, _ = game_identity(old_metadata.get('game_id'))
    new_game_id, _ = game_identity(new_metadata.get('game_id'))
    if old_game_id and new_game_id and old_game_id != new_game_id:
        raise ValueError(f'{_PROJECT_MISMATCH}: known game id mismatch')

    return {
        'schema_version': 1,
        'method': 'user_confirmed_same_game',
        'old_project_id': old_project_id,
        'new_project_id': new_project_id,
        'old_source_manifest_hash': old_manifest_hash,
        'new_source_manifest_hash': new_manifest_hash,
        'engine': old_engine,
        'target_language': 'zh-CN',
        'old_game_id': old_game_id,
        'new_game_id': new_game_id,
    }


def has_confirmation(old_metadata, new_metadata):
    """Return True only for an exact stored explicit-confirmation record."""
    if not isinstance(old_metadata, Mapping) or not isinstance(new_metadata, Mapping):
        return False
    stored = new_metadata.get('migration_lineage')
    if not isinstance(stored, dict) or type(stored.get('schema_version')) is not int:
        return False
    try:
        expected = build_confirmation(old_metadata, new_metadata, confirmed=True)
    except (TypeError, ValueError):
        return False
    return stored == expected
