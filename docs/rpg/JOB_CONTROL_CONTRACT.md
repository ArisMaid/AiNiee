# Cooperative job control implementation contract

Write ONLY `ModuleFolders/Service/GameProject/JobControl.py`. Use read/write/edit
only; no grep/glob/todo, execution, network, agents or deletes. Read this contract
and optionally `ModuleFolders/Service/GameProject/ProjectStore.py` for exact APIs.
Codex wires services/UI and writes acceptance tests. Never edit other files.

Implement small stdlib-only cooperative control, no generic task scheduler.
ProjectStore methods: jobs()->list[dict], update_job(job_id,run_state=...,stage=...,
checkpoint=nonnegativeint,result=dict,error=str); update_job validates transitions
atomically in BEGIN IMMEDIATE. This module does not own/close the provided store.

States: QUEUED->RUNNING/CANCELLED/FAILED;
RUNNING->PAUSE_REQUESTED/CANCEL_REQUESTED/INTERRUPTED/PAUSED/COMPLETED/FAILED/CANCELLED;
PAUSE_REQUESTED->PAUSED/INTERRUPTED/FAILED/COMPLETED;
PAUSED->RUNNING/CANCEL_REQUESTED/INTERRUPTED/COMPLETED/FAILED/CANCELLED;
CANCEL_REQUESTED->CANCELLED/INTERRUPTED/FAILED;
INTERRUPTED->QUEUED. COMPLETED/FAILED/CANCELLED are terminal.

Public `request_action(store, job_id, action)` with actions pause/cancel/resume:
- locate exact job, reject unknown ID/action with ValueError.
- pause RUNNING -> PAUSE_REQUESTED; pause existing PAUSE_REQUESTED/PAUSED idempotent.
- cancel QUEUED -> CANCELLED; cancel RUNNING/PAUSED -> CANCEL_REQUESTED; cancel
  PAUSE_REQUESTED needs transition supported via caller changes? Current store does
  NOT allow PAUSE_REQUESTED->CANCEL_REQUESTED. Codex will add this one valid edge
  during integration. Treat that edge as available. Idempotent CANCEL_REQUESTED/CANCELLED.
- resume PAUSED->RUNNING only; resume already RUNNING idempotent. Refuse all
  other states, especially INTERRUPTED, because a vanished process cannot resume
  in-place. It must be restarted with a new execution after recovery.
- Do NOT acquire OS ProjectLock here: the execution owner intentionally holds it
  while paused, and another connection must still write the control request.
- Concurrent control requests may race; on StoreViolation invalid-transition,
  re-read and retry bounded 3 times. Never revert a terminal state or swallow errors.

`JobCancelled(RuntimeError)` exception stores job_id, says JOB_CANCELLED.
`JobControl(store,job_id,poll_interval=0.1)` validates interval finite 0.01..1.
- `check(force=False)`: query DB no more often than poll_interval unless force;
  remember next monotonic poll. CANCEL_REQUESTED -> CANCELLED then raise JobCancelled;
  CANCELLED raises JobCancelled. PAUSE_REQUESTED -> PAUSED then wait cooperatively
  (time.sleep at most poll_interval), polling DB until RUNNING or cancelled.
  While paused keep no SQLite transaction open. Handle transition races by re-read,
  never turn terminal/interrupted back to running. Any other state (including
  INTERRUPTED/QUEUED/FAILED/COMPLETED) raises ValueError JOB_NOT_RUNNING.
- `checkpoint(stage,completed)` writes exact stage/checkpoint then check(force=True).
  Validate stage nonemptystr and completed nonbool nonnegativeint. Does not auto
  change run_state while writing the checkpoint. If cancelled do not write more
  progress before raising; check first, update stage/checkpoint, check again.
- `complete(result=None)` checks(force=True), update_job run_state COMPLETED,
  stage complete, optional result dict; if concurrent cancellation won, honor it
  (must not accidentally mark cancelled work completed). Retry only transition
  races, never repeat application work. Returns updated job dict.
- `fail(error)` if RUNNING/PAUSED/PAUSE_REQUESTED/CANCEL_REQUESTED mark FAILED
  (unless cancellation requested: acknowledge CANCELLED instead). For terminal
  states leave unchanged. Preserve job/checkpoint. Return current/updated job.
- property/accessor `job_id` public. No files, no threads, no UI dependencies.

Use store.update_job as authority. Catch only its specific StoreViolation and
inspect its code for transition conflicts (read the actual class if necessary),
not broad exceptions. Codex will test two connections and actual pause waiting,
cancel acknowledgement, terminal handling, restart and late model responses.
