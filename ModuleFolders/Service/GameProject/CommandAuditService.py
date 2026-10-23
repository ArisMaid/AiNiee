"""Locatable, reference-only inventories of captured engine event commands."""

from collections import Counter
import hashlib
import json
import re
import uuid

from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.EventCommandInventory import inventory_document
from .ExternalTask import run_external_task
from .PathGuard import atomic_write, safe_join

MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 128 * 1024 * 1024


def _payload(store, record):
    target = safe_join(store.root, record['captured_path'], must_exist=True)
    if target.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError('COMMAND_AUDIT_DOCUMENT_TOO_LARGE: ' + record['relative_path'])
    with target.open('rb') as stream:
        payload = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ValueError('COMMAND_AUDIT_DOCUMENT_TOO_LARGE: ' + record['relative_path'])
    if hashlib.sha256(payload).hexdigest() != record['sha256']:
        raise ValueError('COMMAND_AUDIT_SNAPSHOT_CHANGED: ' + record['relative_path'])
    return payload


def audit_commands(store, *, on_job=None):
    def compute(control):
        metadata = store.metadata()
        files = store.files()
        prefix = metadata.get('data_dir', 'data').rstrip('/') + '/'
        sources = sorted((record for record in files
            if record.get('captured_path') and record['relative_path'].startswith(prefix)
            and re.fullmatch(r'(?:Map[0-9]+|CommonEvents|Troops)\.json', record['relative_path'][len(prefix):])),
            key=lambda record: record['relative_path'])
        pointers = {(o.relative_path, o.locator.get('pointer'))
                    for unit in store.units() for o in unit.occurrences if o.locator.get('pointer')}
        rows, documents = [], []
        counts = Counter()
        for index, record in enumerate(sources):
            control.check(force=True)
            store.update_job(control.job_id, stage='command-audit', checkpoint=index)
            document = json.loads(_payload(store, record).decode('utf-8-sig'))
            found = inventory_document(record['relative_path'], document, check=control.check)
            for row in found:
                for command in row['raw_commands']:
                    counts[str(command['code'])] += 1
                if row['code'] == 357:
                    args = row['raw_commands'][0].get('parameters', [])
                    args = args[3] if isinstance(args, list) and len(args) > 3 and isinstance(args[3], dict) else {}
                    row['argument_pointers'] = {key: row['pointer'] + '/parameters/3/' +
                        key.replace('~', '~0').replace('/', '~1') for key in args}
                    row['approved_fields'] = sorted(key for key in args if
                        (row['path'], row['argument_pointers'][key]) in pointers)
                    row['unreviewed_fields'] = sorted(set(args) - set(row['approved_fields']))
                rows.append(row)
            documents.append({'path': record['relative_path'], 'sha256': record['sha256'], 'record_count': len(found)})
        return {'schema_version': 1, 'project_id': metadata['project_id'], 'job_id': control.job_id,
                'dataset_revision': metadata['dataset_revision'], 'profile_hash': metadata.get('profile_hash'),
                'source_manifest_hash': metadata.get('source_manifest_hash'), 'documents': documents,
                'counts': dict(sorted(counts.items())), 'record_count': len(rows), 'records': rows,
                'reference_only': True, 'writes_enabled': False, '_source_records': sources, '_files': files}

    def publish(report):
        metadata = store.metadata()
        if (metadata['dataset_revision'] != report['dataset_revision']
                or metadata.get('profile_hash') != report['profile_hash'] or store.files() != report['_files']):
            raise ValueError('COMMAND_AUDIT_INPUT_CHANGED')
        for record in report.pop('_source_records'):
            _payload(store, record)
        report.pop('_files')
        payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(payload) > MAX_REPORT_BYTES:
            raise ValueError('COMMAND_AUDIT_REPORT_TOO_LARGE')
        path = safe_join(store.root, 'work/command-audits/' + uuid.uuid4().hex + '.json')
        atomic_write(path, payload)
        return {key: report[key] for key in ('project_id', 'job_id', 'dataset_revision', 'profile_hash',
                'source_manifest_hash', 'counts', 'record_count', 'reference_only', 'writes_enabled')} | {
                    'report_path': str(path), 'report_sha256': hashlib.sha256(payload).hexdigest(),
                    'document_count': len(report['documents'])}

    return run_external_task(store, 'COMMAND_AUDIT', {}, compute, publish, on_job=on_job)


def load_audit_report(store, result):
    """Load the exact completed report; historical revisions remain read only."""
    from pathlib import Path
    path = Path(result['report_path'])
    name = path.name
    if not re.fullmatch(r'[0-9a-f]{32}\.json', name):
        raise ValueError('COMMAND_AUDIT_REPORT_INVALID')
    expected = safe_join(store.root, 'work/command-audits/' + name, must_exist=True)
    if path.absolute() != expected.absolute() or expected.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError('COMMAND_AUDIT_REPORT_INVALID')
    with expected.open('rb') as stream:
        payload = stream.read(MAX_REPORT_BYTES + 1)
    if len(payload) > MAX_REPORT_BYTES or hashlib.sha256(payload).hexdigest() != result['report_sha256']:
        raise ValueError('COMMAND_AUDIT_REPORT_CHANGED')
    report = json.loads(payload.decode('utf-8'))
    if (report.get('schema_version') != 1 or report.get('project_id') != store.metadata()['project_id']
            or report.get('job_id') != result['job_id'] or report.get('writes_enabled') is not False):
        raise ValueError('COMMAND_AUDIT_REPORT_INVALID')
    return report
