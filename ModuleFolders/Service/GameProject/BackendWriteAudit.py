"""Audit external JSON output against the native, approved write plan."""
from __future__ import annotations
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path

from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.JsonPatcher import patch_json
from .PathGuard import assert_disjoint, safe_join
from .ProjectLock import ProjectLock
from .TranslationCommitter import TranslationCommitter


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _canonical(raw):
    obj = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError('INVALID_JSON_NUMBER')))
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def audit_json_output(store, candidate_root):
    """Read-only audit. Passing this check alone never publishes backend files.

    Every captured data/*.json is required, including untranslated files. Only
    native approved occurrences may differ. Format/BOM changes are tolerated;
    event loss, extra keys, bool/number changes and unexpected files are refused.
    """
    candidate_root = Path(candidate_root).absolute()
    assert_disjoint(store.metadata()['source_root'], candidate_root)
    with ProjectLock(store.root):
        meta = store.metadata()
        plans = defaultdict(list)
        committer = TranslationCommitter(store)
        for unit in store.units():
            translation = store.translation(unit.unit_id) or {}
            if not translation.get('text') or translation.get('stale'):
                continue
            if translation.get('source_hash') != unit.source_hash:
                raise ValueError('SOURCE_HASH_MISMATCH')
            proposal = TranslationProposal(unit.unit_id, translation['text'], unit.source_hash,
                                           translation['revision'], origin='validation')
            if any(issue.severity == 'error' for issue in committer.validate_proposal(proposal)):
                raise ValueError('INVALID_ACCEPTED_TRANSLATION')
            for occurrence in unit.occurrences:
                if occurrence.adapter_id == 'rpgmaker-native':
                    plans[occurrence.relative_path].append((occurrence, translation['text']))
        records = [record for record in store.files() if record['relative_path'].startswith('data/')
                   and record['relative_path'].endswith('.json') and record.get('captured_path')]
        if not records:
            raise ValueError('NO_CAPTURED_JSON_FILES')
        report = []
        allowed = {r['relative_path'] for r in records}
        for record in records:
            relative = record['relative_path']
            source = safe_join(store.root, record['captured_path'], must_exist=True).read_bytes()
            if hashlib.sha256(source).hexdigest() != record['sha256']:
                raise ValueError('SNAPSHOT_HASH_MISMATCH')
            expected = patch_json(source, plans.get(relative, []))
            target = safe_join(candidate_root, relative)
            entry = {'path': relative, 'passed': False,
                     'expected_sha256': hashlib.sha256(expected).hexdigest()}
            if not target.is_file():
                entry['reason'] = 'BACKEND_FILE_MISSING'
            elif target.stat().st_size > 64 * 1024 * 1024:
                entry['reason'] = 'BACKEND_FILE_TOO_LARGE'
            else:
                actual = target.read_bytes()
                entry['actual_sha256'] = hashlib.sha256(actual).hexdigest()
                try:
                    entry['passed'] = _canonical(actual) == _canonical(expected)
                    if not entry['passed']:
                        entry['reason'] = 'UNAPPROVED_SEMANTIC_DIFF'
                except (UnicodeError, ValueError):
                    entry['reason'] = 'BACKEND_JSON_INVALID'
            report.append(entry)
        for folder, directories, names in os.walk(candidate_root, followlinks=False):
            for directory in directories:
                safe_join(candidate_root, (Path(folder)/directory).relative_to(candidate_root).as_posix(), must_exist=True)
            for name in names:
                rel = (Path(folder)/name).relative_to(candidate_root).as_posix()
                safe_join(candidate_root, rel, must_exist=True)
                if rel not in allowed:
                    report.append({'path': rel, 'passed': False, 'reason': 'BACKEND_FILE_UNEXPECTED'})
        return {'passed': all(row['passed'] for row in report), 'files': report,
                'dataset_revision': meta['dataset_revision'], 'content_revision': meta['content_revision'],
                'engine_write_adopted': False}
