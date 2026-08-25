# Retry Policy

Task failures are classified before another attempt is scheduled. Only
`contract_error` and `adapter_error` are retryable. `input_error` and
`direction_error` require user action immediately; every other error blocks the
task for diagnosis.

An adapter receives at most two attempts. Once those attempts are exhausted,
the coordinator may switch once to another adapter named in the task envelope.
That declared fallback also receives at most two attempts. A task that has
already used its fallback blocks instead of selecting another adapter.

Workers persist a compact structured result. A result that no longer matches
the envelope inputs, or whose input artifacts are stale, superseded, or invalid,
is retained under `tasks/stale-results/` and never registered as task output.
