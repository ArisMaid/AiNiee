"""Bounded one-shot external tasks owned by the project execution locks."""

from __future__ import annotations

from ModuleFolders.Infrastructure.Platform.OwnedProcess import worker_control

from .JobControl import JobControl
from .JobController import begin_commit
from .ProjectLock import JobLease, ProjectLock

__all__ = ['run_external_task']


def run_external_task(store, operation, payload, compute, publish, on_job=None):
    """Run one external attempt while owning the project and its job lease.

    ``compute`` receives the job control guard; ``publish`` runs only after the
    job has entered ``COMMITTING``.  Every failure is recorded on the job before
    the original exception is re-raised, and both OS locks are always released.
    """

    with ProjectLock(store.root):
        job = store.create_job(operation, payload)
        job_id = job['job_id']
        with JobLease(store.root, job_id):
            control = JobControl(store, job_id)
            try:
                store.update_job(job_id, run_state='RUNNING',stage='external-worker')
                with worker_control(control.check_worker, job_id):
                    if on_job is not None:
                        on_job({'job_id':job_id,'project_root':str(store.root)})
                    control.check(force=True)
                    value = compute(control)
                    begin_commit(store, control)
                    result = publish(value)
                    if not isinstance(result, dict):
                        raise ValueError('EXTERNAL_TASK_RESULT_INVALID: publish must return a dict')
                    result = dict(result, job_id=job_id)
                    store.update_job(
                        job_id,
                        run_state='COMPLETED',
                        stage='complete',
                        checkpoint=1,
                        result=result,
                    )
                    return result
            except BaseException as error:
                try:
                    control.fail(error)
                except BaseException:
                    pass
                raise
