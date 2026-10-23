import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from test_external_tasks import project
from ModuleFolders.Service.GameProject.BackendComparisonService import compare_backend

MODULE = 'ModuleFolders.Service.GameProject.BackendComparisonService'


def test_full_evidence_is_returned_and_hashed_but_job_summary_stays_small(project):
    backend = {'ok': True, 'records': [{'text': 'unmapped原文', 'locator': {'virtual': True}, 'candidate_pointers': []}], 'capabilities': {}}
    with patch(MODULE + '.extract_document', return_value=backend):
        result = compare_backend(project.store, 'rpgmtl', Path(__file__).parents[2] / 'work/vendor/RPGMTL', 'data/Items.json')
    payload = Path(result['report_path']).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == result['report_sha256']
    saved = json.loads(payload)
    assert saved['backend_records'][0]['text'] == 'unmapped原文'
    assert result['backend_records'] == saved['backend_records']
    job = project.store.get_job(result['job_id'])
    assert job['result']['counts'] == result['counts']
    assert job['result']['report_sha256'] == result['report_sha256']
    assert 'backend_records' not in job['result'] and 'native_occurrences' not in job['result']
    assert 'candidate_pointer_groups' not in job['result']
    assert len(json.dumps(job['result'])) < 4096


def test_oversized_report_is_refused_without_publishing(project):
    before = project.store.metadata()
    with patch(MODULE + '.extract_document', return_value={'ok': True, 'records': [], 'capabilities': {}}), \
            patch(MODULE + '.MAX_REPORT_BYTES', 32), pytest.raises(ValueError, match='BACKEND_COMPARE_REPORT_TOO_LARGE'):
        compare_backend(project.store, 'rpgmtl', Path(__file__).parents[2] / 'work/vendor/RPGMTL', 'data/Items.json')
    assert project.store.metadata() == before
    assert project.store.jobs()[-1]['run_state'] == 'FAILED'
    assert not list((project.store.root / 'work/comparisons').glob('*.json'))
