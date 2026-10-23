"""ID-preserving Translator++ CAT interchange; SQLite remains authoritative.

The exchange is an editing project, not a second engine writer. T++ engine
exports are separately tested in isolated copies; accepted exchange edits go
through the same committer and native build service as every other edit.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import uuid

from ModuleFolders.Domain.GameProject.Models import TranslationProposal, hash_text
from .PathGuard import atomic_write, safe_join
from .ProjectLock import ProjectLock
from .TranslationCommitter import TranslationCommitter

FILE_ID = 'AiNiee/translation-units.json'
CONTEXT_PREFIX = 'AiNiee/unit/'
MAX_EXCHANGE_BYTES = 32 * 1024 * 1024


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _read_json(path):
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_EXCHANGE_BYTES + 1)
    if len(raw) > MAX_EXCHANGE_BYTES:
        raise ValueError('TRANSLATORPP_EXCHANGE_TOO_LARGE')
    return json.loads(raw.decode('utf-8-sig'))


def export_exchange(store):
    """Create a new, retained .trans and a DB-registered immutable binding."""
    with ProjectLock(store.root):
        meta = store.metadata()
        if not meta.get('extraction_complete'):
            raise ValueError('EXTRACTION_INCOMPLETE')
        binding_id = uuid.uuid4().hex
        root = safe_join(store.root, 'interchange/translatorpp/' + binding_id)
        root.mkdir(parents=True, exist_ok=False)
        records = []
        tables = {}
        source_counts = {}
        for unit in store.units():
            current = store.translation(unit.unit_id) or {}
            text = current.get('text', '') if not current.get('stale') else ''
            # T++ 8.8.9 sanitizes every file by deduplicating column 0. Allocate
            # equal sources into different tables so distinct contexts survive
            # loading AND reopening the .trans through the unmodified GUI.
            ordinal = source_counts.get(unit.source_text, 0)
            source_counts[unit.source_text] = ordinal + 1
            file_id = FILE_ID if ordinal == 0 else f'AiNiee/translation-units-{ordinal + 1:04d}.json'
            table = tables.setdefault(file_id, {'name': f'翻译单元 {ordinal + 1}',
                'path': file_id, 'relPath': file_id, 'data': [], 'context': [], 'parameters': []})
            record = {'unit_id': unit.unit_id, 'source_hash': unit.source_hash, 'file_id': file_id,
                      'source_text': unit.source_text, 'expected_revision': current.get('revision', 0),
                      'exported_text': text}
            records.append(record)
            table['data'].append([unit.source_text, text])
            table['context'].append([CONTEXT_PREFIX + unit.unit_id])
        exchange_id = 'ainiee-' + binding_id
        binding = {'schema_version': 1, 'binding_id': binding_id,
                   'project_id': meta['project_id'], 'exchange_project_id': exchange_id,
                   'dataset_revision': meta['dataset_revision'], 'file_ids': list(tables), 'rows': records}
        snapshot = {'project': {'projectId': exchange_id, 'gameTitle': 'AiNiee RPG 译文交换',
                    'gameEngine': 'ainiee-rpg-exchange', 'parser': 'ainiee-rpg-exchange-v1',
                    'options': {'sl': 'ja', 'tl': 'zh-CN'}, 'selectedId': FILE_ID,
                    'cache': {'cacheID': exchange_id, 'cachePath': str(root / 'staging')},
                    'files': tables}}
        binding_raw = _encode(binding)
        atomic_write(root / 'binding.json', binding_raw)
        atomic_write(root / 'translations.trans', _encode(snapshot))
        registrations = dict(meta.get('translatorpp_bindings', {}))
        registrations[binding_id] = hashlib.sha256(binding_raw).hexdigest()
        store.update_metadata({'translatorpp_bindings': registrations})
        return {'binding_id': binding_id, 'binding_path': str(root / 'binding.json'),
                'file': str(root / 'translations.trans'), 'exchange_project_id': exchange_id,
                'unit_count': len(records), 'table_count': len(tables), 'engine_write': False}


def load_binding(store, binding_id):
    if not isinstance(binding_id, str) or not re.fullmatch('[a-f0-9]{32}', binding_id):
        raise ValueError('TRANSLATORPP_BINDING_ID_INVALID')
    path = safe_join(store.root, 'interchange/translatorpp/' + binding_id + '/binding.json', must_exist=True)
    raw = path.read_bytes()
    if len(raw) > MAX_EXCHANGE_BYTES:
        raise ValueError('TRANSLATORPP_EXCHANGE_TOO_LARGE')
    meta = store.metadata()
    expected = meta.get('translatorpp_bindings', {}).get(binding_id)
    if not expected or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('TRANSLATORPP_BINDING_CHANGED')
    binding = json.loads(raw)
    if binding.get('schema_version') != 1 or binding.get('binding_id') != binding_id:
        raise ValueError('TRANSLATORPP_BINDING_INVALID')
    if binding['project_id'] != meta['project_id'] or binding['dataset_revision'] != meta['dataset_revision']:
        raise ValueError('TRANSLATORPP_DATASET_CHANGED')
    return binding


def import_exchange(store, binding_id, snapshot):
    """Validate the whole grid's ID/source binding before submitting any edits."""
    with ProjectLock(store.root):
        binding = load_binding(store, binding_id)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('project'), dict):
            raise ValueError('TRANSLATORPP_SNAPSHOT_INVALID')
        project = snapshot['project']
        if project.get('projectId') != binding['exchange_project_id']:
            raise ValueError('TRANSLATORPP_PROJECT_MISMATCH')
        files = project.get('files')
        if not isinstance(files, dict) or set(files) != set(binding['file_ids']):
            raise ValueError('TRANSLATORPP_FILES_CHANGED')
        expected = {row['unit_id']: row for row in binding['rows']}
        seen = set()
        proposals = []
        unchanged = 0
        for file_id, table in files.items():
            if not isinstance(table, dict) or not isinstance(table.get('data'), list) or not isinstance(table.get('context'), list):
                raise ValueError('TRANSLATORPP_GRID_INVALID')
            for index, row in enumerate(table['data']):
                context = table['context'][index] if index < len(table['context']) else None
                if isinstance(row, list) and not any(v not in (None, '') for v in row) and not context:
                    continue  # T++ may append an empty editor row.
                if not isinstance(row, list) or len(row) < 2 or not all(isinstance(row[c], str) for c in (0, 1)):
                    raise ValueError('TRANSLATORPP_ROW_INVALID')
                if not isinstance(context, list) or len(context) != 1 or not isinstance(context[0], str):
                    raise ValueError('TRANSLATORPP_CONTEXT_CHANGED')
                unit_id = context[0].removeprefix(CONTEXT_PREFIX)
                if context[0] != CONTEXT_PREFIX + unit_id or unit_id not in expected or unit_id in seen:
                    raise ValueError('TRANSLATORPP_UNIT_ID_MISMATCH')
                seen.add(unit_id)
                original = expected[unit_id]
                if original['file_id'] != file_id:
                    raise ValueError('TRANSLATORPP_CONTEXT_CHANGED')
                if hash_text(row[0]) != original['source_hash'] or row[0] != original['source_text']:
                    raise ValueError('TRANSLATORPP_SOURCE_CHANGED')
                if row[1] == original['exported_text'] or not row[1].strip():
                    unchanged += 1
                    continue
                proposals.append(TranslationProposal(unit_id, row[1], original['source_hash'],
                                 original['expected_revision'], origin='translatorpp'))
        if seen != set(expected):
            raise ValueError('TRANSLATORPP_UNIT_ID_MISMATCH')
        committer = TranslationCommitter(store)
        results = [committer.submit(proposal).to_dict() for proposal in proposals]
        return {'results': results, 'unchanged': unchanged, 'engine_write': False,
                'accepted': sum(r['status'] in {'accepted', 'duplicate'} for r in results)}


def open_exchange(store, binding_id, client):
    with ProjectLock(store.root):
        binding = load_binding(store, binding_id)
        path = safe_join(store.root, 'interchange/translatorpp/' + binding_id + '/translations.trans', must_exist=True)
        data = _read_json(path)
        if data.get('project', {}).get('projectId') != binding['exchange_project_id']:
            raise ValueError('TRANSLATORPP_PROJECT_MISMATCH')
    client.probe()
    return client.open_data(data)


def pull_exchange(store, binding_id, client):
    binding = load_binding(store, binding_id)
    client.probe()
    snapshot = client.snapshot(binding['exchange_project_id'])
    captured = safe_join(store.root, 'interchange/translatorpp/' + binding_id + '/received-' + uuid.uuid4().hex + '.trans')
    atomic_write(captured, _encode(snapshot))
    result = import_exchange(store, binding_id, snapshot)
    result['received_file'] = str(captured)
    return result


def import_exchange_file(store, binding_id, filename):
    return import_exchange(store, binding_id, _read_json(filename))
