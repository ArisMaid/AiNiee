"""Recover persisted jobs only while holding the OS project lock."""
from .ProjectLock import ProjectLock,JobLease
from .ProjectStore import StoreViolation


def begin_commit(store, control):
    """Serialize a final cancellation check with entering the publish phase.

    Control requests are rejected once COMMITTING wins the SQLite transaction.
    Until then a competing pause/cancel always returns to cooperative checking.
    """
    for _ in range(3):
        control.check(force=True)
        try:
            return store.update_job(control.job_id,run_state='COMMITTING',stage='committing')
        except StoreViolation as error:
            if error.code != 'invalid_transition':raise
    raise ValueError('JOB_CONTROL_RACE: retry after the current control request')


def recover_jobs(store):
    recovered = []
    active=[]
    with ProjectLock(store.root):
        for job in store.active_job_summaries():
            job_id=job['job_id']
            try:
                with JobLease(store.root,job_id):
                    if store.interrupt_job_if_active(job_id,
                            error='PROCESS_INTERRUPTED: captured inputs and proposals retained'):
                        recovered.append(job_id)
            except ValueError as error:
                if not str(error).startswith('PROJECT_BUSY:'):raise
                # The owner may have finished while the lease was probed; only
                # report the job active when its compact state is still active.
                if store.active_job_summaries(job_id):
                    active.append(job_id)
    return {'interrupted_jobs':recovered,
            'active_jobs':active,
            'recovery':'Extract attempts with a document journal can reuse JSON/JS results via resume-extract. '
                       'Translation resumes from SQLite accepted units. '
                       'Builds with a resume journal can verify and reuse individual staged files via resume-build. '
                       'Validation checkpoints can reuse checked units with resume-validation when inputs are unchanged. '
                       'Reviewed migrations reuse atomic accepted receipts via resume-migration. '
                       'Legacy builds without a journal require a new build; no partial output is published.'}
