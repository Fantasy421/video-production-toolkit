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
and releases only that same lock inode. Dead or expired claims can be safely
reclaimed; displaced workers cannot complete a task with an old token.

A result that no longer matches the envelope inputs, whose inputs are not
approved, or whose input lineage has a newer approved version, is retained under
`tasks/stale-results/` and never registered as task output.
