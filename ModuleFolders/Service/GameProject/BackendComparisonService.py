"""Reference-only comparisons of captured documents with backend extraction."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from ModuleFolders.Infrastructure.GameAdapters.CompatibilityBridge import (
    MAX_IO_BYTES,
    extract_document,
)
from ModuleFolders.Service.GameProject.CoverageComparison import compare_extractions
from ModuleFolders.Service.GameProject.ExternalTask import run_external_task
from ModuleFolders.Service.GameProject.PathGuard import atomic_write, safe_join

__all__ = ['compare_backend']
MAX_REPORT_BYTES = 128 * 1024 * 1024


def compare_backend(store, backend, backend_root, relative_path, *, on_job=None):
    """Compare one captured JSON document without importing any translations."""
    published = {}

    def compute(control):
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or not relative_path.lower().endswith('.json')
        ):
            raise ValueError('BACKEND_COMPARE_DOCUMENT_UNSUPPORTED')

        metadata = store.metadata()
        dataset_revision = metadata['dataset_revision']
        native_units = [
            unit.to_dict() if hasattr(unit, 'to_dict') else unit
            for unit in store.units()
        ]

        records = [
            record for record in store.files()
            if isinstance(record, dict)
            and record.get('relative_path') == relative_path
        ]
        if len(records) != 1:
            raise ValueError('BACKEND_COMPARE_DOCUMENT_UNSUPPORTED')
        record = records[0]
        captured_path = record.get('captured_path')
        if not isinstance(captured_path, str) or not captured_path.strip():
            raise ValueError('BACKEND_COMPARE_DOCUMENT_UNSUPPORTED')

        captured = safe_join(store.root, captured_path, must_exist=True)
        if captured.stat().st_size > MAX_IO_BYTES:
            raise ValueError('BACKEND_COMPARE_DOCUMENT_TOO_LARGE')
        with captured.open('rb') as handle:
            payload = handle.read(MAX_IO_BYTES + 1)
        if len(payload) > MAX_IO_BYTES:
            raise ValueError('BACKEND_COMPARE_DOCUMENT_TOO_LARGE')

        source_sha256 = hashlib.sha256(payload).hexdigest()
        record_sha256 = record.get('sha256')
        if (
            not isinstance(record_sha256, str)
            or record_sha256.lower() != source_sha256
        ):
            raise ValueError('BACKEND_COMPARE_SNAPSHOT_CHANGED')

        control.check(force=True)
        extraction = extract_document(
            backend,
            relative_path,
            payload,
            safe_join(store.root, 'work/backends'),
            Path(backend_root).absolute(),
        )
        control.check(force=True)

        comparison = compare_extractions(
            native_units, extraction, relative_path,
            document=json.loads(payload.decode('utf-8-sig')),
        )
        result = dict(comparison)
        result.update(
            backend_capabilities=extraction.get('capabilities', {}),
            backend=backend,
            relative_path=relative_path,
            source_sha256=source_sha256,
            dataset_revision=dataset_revision,
            job_id=control.job_id,
            reference_only=True,
            writes_enabled=False,
        )
        return result

    def publish(result):
        if store.metadata().get('dataset_revision') != result.get('dataset_revision'):
            raise ValueError('BACKEND_COMPARE_INPUT_CHANGED')

        report_path = safe_join(
            store.root, f'work/comparisons/{uuid.uuid4().hex}.json'
        )
        report = json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8')
        if len(report) > MAX_REPORT_BYTES:
            raise ValueError('BACKEND_COMPARE_REPORT_TOO_LARGE')
        atomic_write(report_path, report)
        published.update(result, report_path=str(report_path), report_sha256=hashlib.sha256(report).hexdigest())
        # Record annotations and shared pointer groups belong to the hashed
        # report artifact. Polling a task needs only its compact summary.
        summary = {key: result[key] for key in ('backend', 'relative_path', 'source_sha256',
            'dataset_revision', 'job_id', 'reference_only', 'writes_enabled', 'counts', 'backend_capabilities',
            'type_check', 'type_conflict_count', 'type_conflict_pointer_count')}
        return dict(summary, report_path=str(report_path), report_sha256=published['report_sha256'])

    run_external_task(
        store,
        'BACKEND_COMPARE',
        {'backend': backend, 'relative_path': relative_path},
        compute,
        publish,
        on_job=on_job,
    )
    return dict(published)
