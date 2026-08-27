# Retry Policy

Task failures are classified before another attempt is scheduled. Only
`contract_error` and `adapter_error` are retryable. `input_error` and
`direction_error` require user action immediately; every other error blocks the
task for diagnosis. Retry decisions read the immutable task envelope, so callers
cannot inject adapters outside its declared preferences.

An adapter receives at most two attempts. Once those attempts are exhausted,
the coordinator may switch once to another adapter named in the task envelope.
That declared fallback also receives at most two attempts. The coordinator
atomically records the current adapter, per-adapter attempts, fallback state, and
history in `tasks/retries/<task_id>.json`; a task that has already used its
fallback blocks instead of selecting another adapter.

Workers persist a compact structured result together with the `worker_id` and
opaque `claim_token` returned by `claim_task`. Claims contain PID, lease, and
token metadata. Completion locks and verifies that active claim before publishing
and releases only that same lock inode. Claims are reclaimed only after their PID
is proven dead; lease expiry alone cannot displace a live worker. Displaced
workers cannot complete a task with an old token.

A result that no longer matches the envelope inputs, whose inputs are not
approved, or whose input lineage has a newer approved version, is retained under
`tasks/stale-results/` and never registered as task output.

Only `succeeded` is a terminal task result and may be stored under
`tasks/results/`; it must return at least one existing artifact whose
`output_contract` matches the immutable task envelope. `blocked`,
`waiting_external`, `waiting_user`, `failed`, and `cancelled` are resumable
checkpoints stored under `tasks/status/`. They release the active claim and do
not prevent a later worker from reclaiming the task. Any artifact ID returned by
a checkpoint must still exist and match the envelope output contract.
