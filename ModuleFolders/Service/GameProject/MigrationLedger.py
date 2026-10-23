"""Pure reconstruction of accepted migration receipts.

See docs/rpg/MIGRATION_RECEIPTS_CONTRACT.md for the full contract.  This module performs
no I/O and never touches a store.
"""

from __future__ import annotations

import copy

__all__ = ['reconstruct_receipts']

_TARGET_LANGUAGE = 'zh-CN'
_ORIGIN = 'migration'
_MATCH_METHODS = frozenset(('exact_location', 'unique_scene_anchor'))
_HEX_DIGITS = frozenset('0123456789abcdef')
_MATCH_FIELDS = (
    'old_unit_id',
    'new_unit_id',
    'text',
    'source_hash',
    'expected_revision',
    'match_method',
)


def _invalid(message: str) -> ValueError:
    return ValueError(f'MIGRATION_LEDGER_INVALID: {message}')


def _rejected(message: str) -> ValueError:
    return ValueError(f'MIGRATION_LEDGER_REJECTED: {message}')


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and value != ''


def _is_exact_int(value: object) -> bool:
    return type(value) is int


def _validated_matches(matches: object) -> list[dict]:
    if not isinstance(matches, list):
        raise _invalid('matches must be a list of dicts')
    old_ids: set[str] = set()
    new_ids: set[str] = set()
    validated: list[dict] = []
    for index, match in enumerate(matches):
        if not isinstance(match, dict):
            raise _invalid(f'matches[{index}] must be a dict')
        for field in _MATCH_FIELDS:
            if field not in match:
                raise _invalid(f'matches[{index}] is missing {field}')

        old_unit_id = match['old_unit_id']
        new_unit_id = match['new_unit_id']
        text = match['text']
        source_hash = match['source_hash']
        expected_revision = match['expected_revision']
        match_method = match['match_method']

        if not _is_nonempty_str(old_unit_id):
            raise _invalid(f'matches[{index}].old_unit_id must be a nonempty string')
        if not _is_nonempty_str(new_unit_id):
            raise _invalid(f'matches[{index}].new_unit_id must be a nonempty string')
        if not isinstance(text, str) or text.strip() == '':
            raise _invalid(f'matches[{index}].text must contain non-whitespace text')
        if (not isinstance(source_hash, str) or len(source_hash) != 64
                or any(char not in _HEX_DIGITS for char in source_hash)):
            raise _invalid(f'matches[{index}].source_hash must be 64 lowercase hex digits')
        if not _is_exact_int(expected_revision) or expected_revision < 0:
            raise _invalid(f'matches[{index}].expected_revision must be a nonnegative int')
        if not isinstance(match_method, str) or match_method not in _MATCH_METHODS:
            raise _invalid(f'matches[{index}].match_method is unsupported')

        if old_unit_id in old_ids:
            raise _invalid(f'duplicate old_unit_id: {old_unit_id}')
        if new_unit_id in new_ids:
            raise _invalid(f'duplicate new_unit_id: {new_unit_id}')
        old_ids.add(old_unit_id)
        new_ids.add(new_unit_id)
        validated.append(match)
    return validated


def _selected_proposals(proposals: object, delivery_job_id: str) -> list[dict]:
    if not isinstance(proposals, list):
        raise _invalid('proposals must be a list of dicts')
    selected: list[dict] = []
    for index, row in enumerate(proposals):
        if not isinstance(row, dict):
            raise _invalid(f'proposals[{index}] must be a dict')
        if row.get('job_id') == delivery_job_id:
            selected.append(row)
    return selected


def _check_selected_row(
    row: dict,
    match: dict,
    index: int,
    target_language: str,
    old_project_id: str,
) -> None:
    expected_fields = (
        ('target_language', target_language),
        ('origin', _ORIGIN),
        ('unit_id', match['new_unit_id']),
        ('text', match['text']),
        ('expected_source_hash', match['source_hash']),
    )
    for field, expected in expected_fields:
        value = row.get(field)
        if not isinstance(value, str) or value != expected:
            raise _invalid(f'proposals[{index}].{field} does not match the frozen match')

    expected_revision = row.get('expected_revision')
    if not _is_exact_int(expected_revision) or expected_revision != match['expected_revision']:
        raise _invalid(f'proposals[{index}].expected_revision does not match the frozen match')

    revision = row.get('revision')
    if not _is_exact_int(revision) or revision != match['expected_revision'] + 1:
        raise _invalid(f'proposals[{index}].revision is not expected_revision + 1')

    expected_request_item = (
        f'{old_project_id}:{match["old_unit_id"]}:{match["new_unit_id"]}'
    )
    request_item_id = row.get('request_item_id')
    if not isinstance(request_item_id, str) or request_item_id != expected_request_item:
        raise _invalid(f'proposals[{index}].request_item_id does not match the frozen match')

    expected_metadata = {
        'old_unit_id': match['old_unit_id'],
        'old_project_id': old_project_id,
        'new_unit_id': match['new_unit_id'],
    }
    metadata = row.get('metadata')
    if not isinstance(metadata, dict) or metadata != expected_metadata:
        raise _invalid(f'proposals[{index}].metadata does not match the frozen match')


def reconstruct_receipts(
    matches,
    proposals,
    *,
    delivery_job_id,
    old_project_id,
    target_language='zh-CN',
) -> dict:
    """Reconstruct the accepted-prefix ledger from frozen matches and rows."""
    if not _is_nonempty_str(delivery_job_id):
        raise _invalid('delivery_job_id must be a nonempty string')
    if not _is_nonempty_str(old_project_id):
        raise _invalid('old_project_id must be a nonempty string')
    if not isinstance(target_language, str) or target_language != _TARGET_LANGUAGE:
        raise _invalid(f'target_language must be {_TARGET_LANGUAGE}')

    validated_matches = _validated_matches(matches)
    selected = _selected_proposals(proposals, delivery_job_id)
    completed = len(selected)
    if completed > len(validated_matches):
        raise _invalid('selected proposals exceed the frozen match list')

    results: list[dict] = []
    previous_proposal_id = None
    for index, row in enumerate(selected):
        status = row.get('status')
        if status != 'accepted':
            raise _rejected(f'proposals[{index}] status is not accepted')

        proposal_id = row.get('proposal_id')
        if not _is_exact_int(proposal_id) or proposal_id <= 0:
            raise _invalid(f'proposals[{index}].proposal_id must be a positive int')
        if previous_proposal_id is not None and proposal_id <= previous_proposal_id:
            raise _invalid('selected proposal_id values must strictly increase')
        previous_proposal_id = proposal_id

        match = validated_matches[index]
        _check_selected_row(row, match, index, target_language, old_project_id)
        results.append({
            'unit_id': match['new_unit_id'],
            'status': 'accepted',
            'revision': match['expected_revision'] + 1,
            'issues': [],
        })

    pending_matches = [
        copy.deepcopy(match) for match in validated_matches[completed:]
    ]
    return {
        'completed': completed,
        'results': results,
        'pending_matches': pending_matches,
    }
