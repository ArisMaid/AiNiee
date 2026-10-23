"""Codex-owned validation boundary for every game translation mutation."""
from __future__ import annotations
from .ProjectStore import ProjectStore
from ModuleFolders.Domain.GameProject.Models import TranslationProposal, Issue
from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy


class TranslationCommitter:
    def __init__(self, store: ProjectStore):
        self.store = store
        meta = store.metadata()
        self.policy = TokenPolicy(meta.get('token_commands', ()), meta.get('token_policy_id', 'rpgmaker-v1'),
            literal_tokens=meta.get('token_literals',()))

    def validate_proposal(self, proposal):
        unit = self.store.unit(proposal.unit_id)
        if unit is None:
            return (Issue('UNKNOWN_UNIT', 'error', 'Translation unit no longer exists', proposal.unit_id),)
        issues = list(self.policy.validate(unit.source_text, proposal.text, unit.unit_id))
        from ModuleFolders.Domain.GameProject.ValueConstraints import validate_display_value
        issues.extend(validate_display_value(unit.source_text,proposal.text,unit.context,unit.unit_id))
        if unit.source_text.strip() and not proposal.text.strip() and proposal.origin != 'manual':
            issues.append(Issue('EMPTY_TRANSLATION', 'error', 'Model returned empty translation', unit.unit_id))
        return tuple(issues)

    def submit(self, proposal):
        return self.store.commit(proposal, issues=self.validate_proposal(proposal))

    def reset_task_status(self, mode, *, project_id, dataset_revision, expected_rows):
        """Explicit user scheduling command; accepted text is preserved/audited."""
        return self.store.reset_task_status(mode,project_id=project_id,
            dataset_revision=dataset_revision,expected_rows=expected_rows)

    def edit_manual(self, proposal, *, locked: bool):
        """Apply an explicit owner/UI manual edit: text and desired lock together.

        This is the only path allowed to pass ``manual_lock`` to the store, so
        only an explicit user command may override an existing manual lock.
        ``ProjectStore.commit`` is the authority and re-reads the unit, current
        translation, schema/capabilities and current token/value policy inside
        its single writer transaction before changing text, revision, lock,
        proposal, edit, issues and ``content_revision`` atomically.  A rejected
        or conflicting command therefore leaves the accepted row and lock
        untouched. A metadata-only lock command does not validate an empty
        untranslated value as a new translation. Imports, OpenCC, model responses and every other automatic
        path must keep calling ``submit``/``store.commit`` without
        ``manual_lock``.
        """
        if type(locked) is not bool:
            raise ValueError('Manual edit requires an explicit boolean lock')
        return self.store.commit(proposal, manual_lock=locked)

    def submit_batch(self, proposals, expected_dataset_revision=None):
        if expected_dataset_revision is not None:
            if self.store.metadata()['dataset_revision'] != expected_dataset_revision:
                raise ValueError('SOURCE_CHANGED: extraction revision no longer matches request')
        return [self.submit(p) for p in proposals]

    def accept_response(self, units, response, prepared, *, job_id, origin='model', revisions=None):
        """Response IDs must match exactly; order is never used to identify a row."""
        expected = {u.unit_id for u in units}
        if not isinstance(response, dict) or set(response) != expected:
            raise ValueError('RESPONSE_ID_MISMATCH: missing, unexpected or duplicate response IDs')
        proposals = []
        for u in units:
            text, issues = prepared[u.unit_id].restore(response[u.unit_id])
            proposal = TranslationProposal(u.unit_id, text, u.source_hash,
                expected_revision=(revisions or {}).get(u.unit_id, 0), job_id=job_id,
                request_item_id=u.unit_id, origin=origin)
            if issues:
                proposals.append(self.store.commit(proposal, issues=issues))
            else:
                proposals.append(self.submit(proposal))
        return proposals
