# Project handoff archival

`project_handoff_write` accepts `{"action":"archive","task_id":"…","expected_revision":N}`. The ordinary explicit Workflow Session, project write permission and Runner boundary still apply. `expected_revision` is the task revision obtained from `project_handoff_read`, not the project index revision.

Archive only after work has ended and the task is explicitly completed. No timer, TTL, tool success or Session termination archives tasks automatically. Unknown facts, nonterminal Job projections, active Server Jobs, undelivered facts and capture gaps refuse archival. Archival does not resolve or delete any of these facts. The caller must also stop local work on that task: the Server cannot fence an independent local Codex process.

The checkpoint writer atomically moves the task summary from the active index to `retired_tasks`. Task JSON, Markdown (including user notes), immutable event segments and task revision are unchanged. Reading the exact task still returns its checkpoint with `archived=true`. Status lists `archived_tasks` separately and never selects an archived task as current work. Append, task-ID reuse and reusing an archived local client binding are rejected. New work uses a new task and a fresh Session.

Active limits remain 64 tasks and 2 MiB. Retained history is separately bounded to 128 tasks and 128 MiB, with the existing 64 KiB index limit still enforced. Hitting a history/index limit refuses the operation and preserves everything; archival is not an unlimited storage service. No automatic history deletion is introduced.

## Delivery and recovery

Server foreground mutations take a shared non-waiting gate through fact capture. Archive needs the exclusive gate and refuses while work is in flight. The Server checks all active Jobs of the exact authorized project, then freezes the exact project/Runner/path/task/root fingerprint in its existing SQLite database. The freeze refuses new bindings and subsequent business admission for the old bindings. It verifies the outbox and capture gaps both before the Runner mutation and before releasing active binding capacity.

A confirmed archive retires the matching Server bindings without deleting their identities. The active Server binding limit remains 1024; retained binding identities have a separate 65536-row bound and task retirement markers a 4096-row bound. Old Sessions cannot be rebound. Late receipts remain attached to the original identity in the durable outbox, even after retirement. They are surfaced as pending; this implementation does not silently reopen archived history or discard those receipts. Unexpected late facts require investigation, and must not be claimed as delivered.

A lost or malformed Runner acknowledgement leaves a durable `retiring` state, not success. Read the exact task and retry only the archive request with its current revision; never replay the business operation. Already archived tasks acknowledge archive idempotently without changing their files. A definitive failed write cancels the preparation fence when the preflight checkpoint was not archived. A pending outbox/capture gap always remains intact.

The local CLI can archive locally owned tasks, but refuses tasks with `webcodex:` bindings because it cannot attest Server delivery. Those tasks must go through `project_handoff_write`; a model-supplied boolean cannot bypass that check.

## Installation compatibility

The first archive atomically upgrades the project index to version 2. All CLI/Hook and Server/Runner components that access that project must support this version before archival is enabled in daily use. Old writers fail closed; do not downgrade the index manually or claim that rolling back only binaries restores v1 compatibility. This development change does not install, archive production data, or restart services.
