"""Cooperative pause/cancel control for one project job.

Implements ``docs/rpg/JOB_CONTROL_CONTRACT.md`` on top of the job API of
:class:`~ModuleFolders.Service.GameProject.ProjectStore`.

:func:`request_action` is the control side: any connection (the UI, a
supervisor) records a pause/cancel/resume request and never takes the OS
project lock, so the execution owner may keep holding that lock while it is
paused.  :class:`JobControl` is the execution side: the owner calls
:meth:`JobControl.check` between work items, :meth:`JobControl.checkpoint` to
persist progress and :meth:`JobControl.complete` / :meth:`JobControl.fail` to
finish.

The module is stdlib only.  It never owns or closes the store it is given,
opens no file, starts no thread and keeps no SQLite transaction open while it
waits for a resume; :class:`ProjectStore` stays the single authority on job
rows and on the transitions it validates atomically.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping

from .ProjectStore import ProjectStore, StoreViolation

__all__ = ['JOB_ACTIONS', 'JobCancelled', 'JobControl', 'request_action']

#: Control actions accepted by :func:`request_action`.
JOB_ACTIONS: tuple[str, ...] = ('pause', 'cancel', 'resume')

#: Bounded number of re-read/retry attempts after a racing job transition.
_MAX_ATTEMPTS = 3

#: Internal decision markers: request already satisfied / request rejected.
_IDEMPOTENT = 'idempotent'
_REFUSE = 'refuse'


class JobCancelled(RuntimeError):
    """The execution owner must stop: the job reached an acknowledged cancel."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f'JOB_CANCELLED: job {job_id}')


def _find_job(store: ProjectStore, job_id: str) -> dict | None:
    """Return the stored job row for ``job_id``, or ``None`` when unknown."""

    return store.get_job(job_id)


def _next_state(action: str, state: str) -> str:
    """Return the run state ``action`` asks for while the job is in ``state``.

    ``_IDEMPOTENT`` means the request is already satisfied and the current row
    is returned unchanged; ``_REFUSE`` means the request cannot apply to that
    state and must be rejected.
    """

    if action == 'pause':
        if state == 'RUNNING':
            return 'PAUSE_REQUESTED'
        if state in ('PAUSE_REQUESTED', 'PAUSED'):
            return _IDEMPOTENT
        return _REFUSE
    if action == 'cancel':
        if state == 'QUEUED':
            return 'CANCELLED'
        if state in ('RUNNING', 'PAUSED', 'PAUSE_REQUESTED'):
            return 'CANCEL_REQUESTED'
        if state in ('CANCEL_REQUESTED', 'CANCELLED'):
            return _IDEMPOTENT
        return _REFUSE
    # resume: only a job that paused itself in place can continue.  An
    # INTERRUPTED job lost its process and must be restarted, never resumed.
    if state == 'RUNNING':
        return _IDEMPOTENT
    if state == 'PAUSED':
        return 'RUNNING'
    return _REFUSE


def request_action(store: ProjectStore, job_id: str, action: str) -> dict:
    """Record a ``pause``/``cancel``/``resume`` request for one exact job.

    Returns the job row as stored once the request is satisfied.  ``ValueError``
    is raised for an unknown job id, an unknown action or a state the action
    cannot apply to.  ``StoreViolation`` is re-raised unchanged unless it is an
    ``invalid_transition`` conflict, which is retried after a re-read.
    """

    if action not in JOB_ACTIONS:
        raise ValueError(f'JOB_ACTION_UNKNOWN: unsupported action {action!r}')
    if not isinstance(job_id, str) or job_id == '':
        raise ValueError(f'JOB_NOT_FOUND: invalid job id {job_id!r}')
    conflict = StoreViolation('invalid_transition', f'job {job_id} kept changing run state')
    for _ in range(_MAX_ATTEMPTS):
        job = _find_job(store, job_id)
        if job is None:
            raise ValueError(f'JOB_NOT_FOUND: unknown job {job_id!r}')
        state = job['run_state']
        target = _next_state(action, state)
        if target == _IDEMPOTENT:
            return job
        if target == _REFUSE:
            raise ValueError(
                f'JOB_ACTION_REFUSED: cannot {action} job {job_id!r} in state {state}'
            )
        if action=='resume' and state=='PAUSED':
            from .ProjectLock import JobLease
            try:
                with JobLease(store.root,job_id):pass
            except ValueError as error:
                if not str(error).startswith('PROJECT_BUSY:'):raise
            else:
                raise ValueError('JOB_OWNER_MISSING: recover and restart the interrupted execution')
        try:
            return store.update_job(job_id, run_state=target)
        except StoreViolation as error:
            if error.code != 'invalid_transition':
                raise
            conflict = error
    raise conflict


class JobControl:
    """Cooperative execution guard for one job of one project store.

    ``poll_interval`` bounds how often :meth:`check` may read the database and
    how long one pause sleep may last.  The store is used exactly as given and
    is never closed here.
    """

    def __init__(self, store: ProjectStore, job_id: str, poll_interval: float = 0.1) -> None:
        if not isinstance(job_id, str) or job_id == '':
            raise ValueError(f'JOB_NOT_FOUND: invalid job id {job_id!r}')
        if isinstance(poll_interval, bool) or not isinstance(poll_interval, (int, float)):
            raise ValueError(
                f'JOB_POLL_INTERVAL: poll_interval must be a number within [0.01, 1], '
                f'got {poll_interval!r}'
            )
        try:
            interval = float(poll_interval)
        except OverflowError:
            raise ValueError(
                f'JOB_POLL_INTERVAL: poll_interval must be a finite number within [0.01, 1], '
                f'got {poll_interval!r}'
            ) from None
        if not math.isfinite(interval) or not (0.01 <= interval <= 1.0):
            raise ValueError(
                f'JOB_POLL_INTERVAL: poll_interval must be a finite number within [0.01, 1], '
                f'got {poll_interval!r}'
            )
        self._store = store
        self._job_id = job_id
        self._poll_interval = interval
        self._next_poll = 0.0

    @property
    def job_id(self) -> str:
        """Identifier of the job this guard controls."""

        return self._job_id

    # ------------------------------------------------------------------
    # public execution side
    # ------------------------------------------------------------------

    def check(self, force: bool = False) -> None:
        """Honour a pending control request; return when work may continue.

        The database is read at most once per ``poll_interval`` unless ``force``
        is true.  A cancel is acknowledged and raised as :class:`JobCancelled`;
        a pause request pauses the job and waits cooperatively until it runs
        again.  Any other non-running state raises ``ValueError`` with
        ``JOB_NOT_RUNNING``.
        """

        if not force and time.monotonic() < self._next_poll:
            return
        state = self._read_job()['run_state']
        self._next_poll = time.monotonic() + self._poll_interval
        for _ in range(_MAX_ATTEMPTS):
            if state == 'RUNNING':
                return
            if state == 'CANCELLED':
                raise JobCancelled(self._job_id)
            if state == 'CANCEL_REQUESTED':
                if self._settle('CANCELLED', 'CANCEL_REQUESTED'):
                    raise JobCancelled(self._job_id)
                state = self._read_job()['run_state']
                continue
            if state == 'PAUSE_REQUESTED':
                if self._settle('PAUSED', 'PAUSE_REQUESTED'):
                    self._wait_while_paused()
                    return
                state = self._read_job()['run_state']
                continue
            if state == 'PAUSED':
                self._wait_while_paused()
                return
            raise ValueError(f'JOB_NOT_RUNNING: job {self._job_id!r} is {state}')
        raise ValueError(f'JOB_NOT_RUNNING: job {self._job_id!r} kept changing run state')

    def check_worker(self, force: bool = False) -> None:
        """Check cancel without blocking a worker deadline on a pause request.

        The current worker may finish its file in memory; the ordinary boundary
        check then acknowledges pause before any result is committed.
        """
        if not force and time.monotonic()<self._next_poll:return
        self._next_poll=time.monotonic()+self._poll_interval
        for _ in range(_MAX_ATTEMPTS):
            state=self._read_job()['run_state']
            if state in {'RUNNING','PAUSE_REQUESTED','PAUSED','COMMITTING'}:return
            if state=='CANCELLED':raise JobCancelled(self._job_id)
            if state=='CANCEL_REQUESTED':
                if self._settle('CANCELLED','CANCEL_REQUESTED'):raise JobCancelled(self._job_id)
                continue
            raise ValueError(f'JOB_NOT_RUNNING: job {self._job_id!r} is {state}')
        raise ValueError('JOB_CONTROL_RACE: worker state kept changing')

    def checkpoint(self, stage: str, completed: int) -> dict:
        """Persist ``stage``/``completed`` for the current work item.

        The run state is never changed here.  A cancellation is checked before
        the progress write, so no progress is written after a cancel was
        observed, and again afterwards, so a cancel that arrived meanwhile is
        raised immediately.
        """

        if not isinstance(stage, str) or stage == '':
            raise ValueError(f'JOB_STAGE_INVALID: stage must be a non empty string, got {stage!r}')
        if isinstance(completed, bool) or not isinstance(completed, int) or completed < 0:
            raise ValueError(
                f'JOB_CHECKPOINT_INVALID: completed must be a non negative integer, '
                f'got {completed!r}'
            )
        self.check(force=True)
        job = self._store.update_job(self._job_id, stage=stage, checkpoint=completed)
        self.check(force=True)
        return job

    def complete(self, result: Mapping | None = None) -> dict:
        """Finish the job as COMPLETED unless a concurrent cancellation won.

        Only the state write is retried on a transition race: application work
        is never repeated here.  A cancellation that wins the race is
        acknowledged with :class:`JobCancelled` instead of marking cancelled
        work completed.
        """

        if result is not None and not isinstance(result, Mapping):
            raise ValueError(
                f'JOB_RESULT_INVALID: result must be a mapping, got {type(result).__name__}'
            )
        self.check(force=True)
        changes: dict[str, object] = {'run_state': 'COMPLETED', 'stage': 'complete'}
        if result is not None:
            changes['result'] = result
        conflict = StoreViolation('invalid_transition', f'job {self._job_id} kept changing run state')
        for _ in range(_MAX_ATTEMPTS):
            try:
                return self._store.update_job(self._job_id, **changes)
            except StoreViolation as error:
                if error.code != 'invalid_transition':
                    raise
                conflict = error
                state = self._read_job()['run_state']
                if state == 'CANCELLED':
                    raise JobCancelled(self._job_id)
                if state == 'CANCEL_REQUESTED':
                    if self._settle('CANCELLED', 'CANCEL_REQUESTED'):
                        raise JobCancelled(self._job_id)
                    continue
                if state in ('RUNNING', 'PAUSED', 'PAUSE_REQUESTED'):
                    continue
                raise ValueError(f'JOB_NOT_RUNNING: job {self._job_id!r} is {state}')
        raise conflict

    def fail(self, error: str) -> dict:
        """Record a failure; a requested cancellation is acknowledged instead.

        Only RUNNING, PAUSED and PAUSE_REQUESTED jobs are marked FAILED.
        Terminal jobs are returned as stored, and QUEUED/INTERRUPTED jobs are
        left for the supervisor that owns recovery.  Stage and checkpoint are
        preserved: only the error text and the run state change.
        """

        message = str(error) if isinstance(error, BaseException) else error
        if not isinstance(message, str):
            raise ValueError(
                f'JOB_ERROR_INVALID: error must be a string, got {type(error).__name__}'
            )
        conflict = StoreViolation('invalid_transition', f'job {self._job_id} kept changing run state')
        for _ in range(_MAX_ATTEMPTS):
            job = self._read_job()
            state = job['run_state']
            if state == 'CANCEL_REQUESTED':
                if self._settle('CANCELLED', 'CANCEL_REQUESTED'):
                    return self._read_job()
                continue
            if state in ('RUNNING', 'PAUSED', 'PAUSE_REQUESTED', 'COMMITTING'):
                try:
                    return self._store.update_job(self._job_id, run_state='FAILED', error=message)
                except StoreViolation as store_error:
                    if store_error.code != 'invalid_transition':
                        raise
                    conflict = store_error
                    continue
            return job
        raise conflict

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _read_job(self) -> dict:
        job = _find_job(self._store, self._job_id)
        if job is None:
            raise ValueError(f'JOB_NOT_RUNNING: unknown job {self._job_id!r}')
        return job

    def _settle(self, target: str, source: str) -> bool:
        """Move the job from ``source`` to ``target`` and report the outcome.

        ``True`` means the job is stored in ``target``; ``False`` means a
        concurrent transition moved it elsewhere first, so the caller re-reads
        and decides again.  Retries repeat only this state write.
        """

        conflict = StoreViolation('invalid_transition', f'job {self._job_id} kept changing run state')
        for _ in range(_MAX_ATTEMPTS):
            try:
                self._store.update_job(self._job_id, run_state=target)
                return True
            except StoreViolation as error:
                if error.code != 'invalid_transition':
                    raise
                conflict = error
                state = self._read_job()['run_state']
                if state == target:
                    return True
                if state != source:
                    return False
        raise conflict

    def _wait_while_paused(self) -> None:
        """Sleep with no open SQLite transaction until resumed or cancelled."""

        while True:
            time.sleep(self._poll_interval)
            state = self._read_job()['run_state']
            if state == 'RUNNING':
                self._next_poll = time.monotonic() + self._poll_interval
                return
            if state == 'CANCELLED':
                raise JobCancelled(self._job_id)
            if state == 'CANCEL_REQUESTED':
                if self._settle('CANCELLED', 'CANCEL_REQUESTED'):
                    raise JobCancelled(self._job_id)
                continue
            if state == 'PAUSED':
                continue
            raise ValueError(f'JOB_NOT_RUNNING: job {self._job_id!r} is {state}')
