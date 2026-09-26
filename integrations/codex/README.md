# Codex project handoff adapter

This adapter connects Codex hooks to the same checkpoint implementation used by
WebCodex's Runner. It does not install hooks, migrate chat transcripts, launch a
model, modify permission decisions, or commit/push project files.

The optional upstream Workflow Session report adapter has a separate evidence
model and is documented in [workflow-session-observations.md](workflow-session-observations.md).
It does not replace the project-local checkpoint or its universal Hooks.

## Activation: one trusted entry for all projects

Generate `generate_config.py --universal --binary /absolute/webcodex` and review
it through the normal Codex user-level Hook flow once. Project discovery and
intent matching use `enter_work.py`; users need not create Hooks for each project
or provide task IDs. Installation and trust are separate from generating JSON.

To check Server delivery on entry, add `--source-config /trusted/connection.json`.
This one operator-owned configuration contains `server_url`, `token_file` (an
absolute path to an existing credential), and `client_id` (the exact local
Runner). It contains no project mapping. The adapter resolves the current exact
canonical directory using authenticated `list_projects` on that Runner, rejects
ambiguous/truncated inventories, then checks the task and root fingerprint via
`project_handoff_read`. It never registers a project or creates credentials.
HTTPS is required except for numeric loopback; redirects and inherited proxies
are disabled. Missing configuration, authorization, or matching registration is
reported as unavailable, never caught up. The query shares the Hook deadline.

Retire obsolete project-specific handoff entries during a reviewed installation,
preserving unrelated Hooks. A leftover entry cannot suppress the universal
adapter: both use the same session/tool event identity and the writer atomically
deduplicates identical facts. Conflicting facts remain explicit errors. Config
presence is not evidence that the old Hook is trusted, loaded, or matching.

The exact hook input/output contract is documented in [Codex hooks](https://learn.chatgpt.com/docs/hooks).
An installed CLI and the Desktop app must be tested separately; a synthetic
payload does not prove either entrance activated the hook.


### Automatic remote Workflow Session recovery

For remote work recorded in a Workflow Session, add
`--recovery-registry /private/operator/recovery.json` to universal configuration.
See [workflow-session-observations.md](workflow-session-observations.md) for the
private registry and explicit read association. The same user-level entry then
refreshes remote evidence on SessionStart/UserPromptSubmit even when there is no
local `handoff/index.json`. Existing local checkpoint capture is preserved;
reading remote work does not bind a local observation writer.

Recovery verifies the current Server Project-to-root mapping before and after
reading, then checks that the operator association has not changed before
publishing the snapshot. Changed or unavailable identities leave recovery
unconfirmed; no previous snapshot is substituted as current evidence.

## Behavior and limits

- `SessionStart` and `UserPromptSubmit` discover the project checkpoint and direct
  the receiving agent to read current files and project rules. Discovery does not
  infer a Session, select the newest file, or grant authority.
- `PostToolUse` saves bounded metadata with a stable event ID. It never stores
  raw tool arguments, commands, output streams, environment, or transcript text.
  Only an explicit numeric `exit_code` is interpreted as a command outcome.
  Other envelopes remain `unknown`; a successful Job-start call is not a
  completed Job. Plan/unknown permission modes do not append.
- `Stop` reports that a checkpoint is available and reminds the agent to retain
  unresolved work. It does not assert task completion, block the original tool
  result, restart the model, or create a continuation loop.
- An input above 128 KiB, missing identity, unsupported envelope, writer error,
  or timeout produces a visible warning. A timeout means saving is **unconfirmed**,
  not proven absent. Reconcile the event ID before any retry.
- Unknown tool envelopes, changed files, active tasks, and judgments still need
  explicit review by the receiving agent. This is fact persistence, not hidden
  reasoning or complete Session migration.
- The hook CWD must resolve to the configured exact project directory. A
  different worktree, copied project root, or unrelated notes folder is rejected.
- Disable the project's handoff index with the explicit `disable` action to stop
  automatic saving; remove only this adapter's reviewed project hook entries when
  uninstalling. Existing project files and other hooks remain intact.

## Non-network adapter tests

`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s integrations/codex -p 'test_*.py' -v`

These tests use synthetic hook payloads and temporary local files. They do not
claim real Codex hook invocation, GPT web acceptance, or production readiness.

## Optional source-state connection

`generate_config.py` accepts `--source-config /absolute/private/source.json`.
The reviewed configuration must contain exactly `project_path`, the full
`project_id` (`agent:<client>:<project>`), `server_url`, and an absolute
`token_file` pointing to an existing authorized token. Keep it outside Git.
No token is copied into checkpoint files or hook context. HTTPS is required
except for numeric loopback HTTP; redirects and inherited proxies are disabled.

The probe is read-only. Missing configuration, connection failure, permission
refusal, or mismatched project identity remains `unavailable`, never `caught_up`.
`pending` counts Server facts awaiting acknowledgement; a Runner may already have
saved equivalent Job evidence locally. Compare the same Job ID and sequence;
do not rerun the Job. A later authorized WebCodex task binding flushes this queue.
`caught_up` covers only known recorded events, not all historical chat activity.

Review the exact generated commands in Codex's normal `/hooks` trust interface.
An existing disabled hooks setting requires an explicit project configuration
choice through that normal flow. This package never updates trust hashes, enables
global hooks, or suppresses platform refusals. Each hook has a 30-second budget;
source calls use a six-second socket timeout and writer calls an eight-second
process timeout. Slow or unavailable sources can therefore delay task entry.

## Real local adapter acceptance

Run `python3 integrations/codex/validate_local.py --binary /absolute/webcodex
--report /absolute/new-report.json` from this checkout. It invokes the real CLI
and Python hook adapter against disposable code and Chinese notes projects,
using synthetic hook events. It checks two tasks, nonzero and unknown outcomes,
idempotency, preserved human text, disabled behavior and exact cleanup.
It does not invoke a Codex model, trust project hooks, or connect GPT/MCP.

Job summaries in `jobs` retain the highest observed lifecycle sequence and do
not regress from terminal to running when callbacks arrive out of order. Raw
events remain historical evidence. File/Git observations are not a continuous
filesystem watcher: the receiver must inspect current relevant files and Git
state before reusing historical validation evidence.

An unbound local Session must select its task before ordinary work. The adapter
cannot retroactively attribute a tool that already ran without a binding: it
explicitly reports that fact as not saved and forbids replay as a repair. This
must be exercised in real Codex acceptance; startup guidance alone is not a
permission barrier or a guarantee that the model selected a task.

### Text-only Bash receipts

A Hook firing proves capture, not process success. Codex unified-exec can send
only truncated stdout/stderr in `tool_response`; the exit-code header visible
to the model is not necessarily included. Such events remain `unknown` with
`text_output_without_execution_receipt` in their summary. Output text (even
JSON or a printed “Process exited with code 0”) is never treated as an execution
receipt. Structured integer exit codes retain completed/failed classification;
non-terminal receipts stay unknown. Existing events are not rewritten.

Upstream implementation reference:
https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/context.rs
(`ExecCommandToolOutput::post_tool_use_response`). This is a source reference,
not a claim that every installed Codex build uses the same wire format.

## Universal entry candidate: discover, confirm, continue

Generate one user-level configuration with `generate_config.py --universal
--binary /absolute/webcodex`. This points all four events to `universal_hook.py`;
no project path or credential is embedded in the hook definition. It prints only:
installation and review still use the normal Codex flow. Matching old project hooks can also run; stable event IDs prevent duplicate facts. Preserve unrelated
hooks and disable only the previously installed handoff entries during migration.

The entry resolves the nearest Git root for code subdirectories, stopping at
nested repositories and worktree boundaries. Non-Git notes use exact canonical
CWD. Existing `handoff/index.json` opts in. It never scans sibling projects,
executes project-provided code or inherits source credentials. Without an index,
SessionStart provides read-first entry guidance, but creates no files. Without
an index, subsequent prompt/tool/stop events remain silent. This does not suppress
errors from an opted-in task and never marks unsaved work as captured.

GPT discovery precedes task creation: use authorized read/list/search tools,
present the project identity, and wait for the user's project and objective
confirmation. Then the agent reads existing tasks and creates/binds the intended
one using the existing authorized Workflow Session and handoff tools. Users do
not supply task IDs or run binding commands. Ambiguity still needs clarification.
Do not infer a Workflow Session from a ChatGPT chat ID. Confirmation of a project
does not grant business-write authority. A read-only task cannot silently upgrade
its Session permissions just to save a checkpoint. Existing immutable binding,
write admission, receipts and unknown-operation protections remain unchanged.

This universal candidate has no remote source probe: local records remain a
historical snapshot, not proof of remote catch-up. Automatic model selection and
actual desktop/plugin loading require real entrance acceptance; generated config
and synthetic event checks alone do not establish those behaviours. No global
configuration or production service is changed by these scripts.


## Confirmed work entry candidate (2026-09-16)

`enter_work.py --binary /absolute/webcodex --project /confirmed/root
--session <actual-local-session-id> --objective <goal>` performs read-only
inspection. The agent adds `--confirmed` only after project/objective confirmation
and when local checkpoint writing is already authorized. This flag records the
caller's choice; it is not a permission mechanism or independent proof of consent.

A new task uses one existing writer transaction to create the task, initial note,
and Session binding. Task IDs are generated by the adapter. Existing tasks are
returned for intent matching, never guessed by recency or merely being unique.
The agent uses `--task-id` to resume the intended task, or `--new-task` for a
separate confirmed task in an unbound Session. An already-bound Session cannot
silently switch. Failures/timeouts are surfaced without automatic retry.

Existing AGENTS/HANDOFF/baseline/iteration/README locations are referenced, not
copied or rewritten. `--related /absolute/path` optionally records up to eight
associated locations; it does not read their contents, expand permissions,
automatically capture other repositories or merge separate task ledgers. Ordinary
projects do not need these documents or related locations. No Obsidian/GitHub
setup or project-specific Hooks is required.

Web GPT entry uses the existing `work_on_project` and project_handoff read/write
interfaces after user confirmation, with an actual authorized Workflow Session.
The Python helper is local only and must not be passed a fabricated ChatGPT
Session ID. Directory registration and tool availability remain WebCodex entry
responsibilities; this adapter cannot bypass unavailable MCP tools or register an
unauthorized directory. Real web entrance acceptance remains required.

Offline acceptance: `python3 integrations/codex/validate_entry.py --binary
/absolute/webcodex --report /new/report.json`. This checks code subdirectories,
Chinese notes, existing documents, create/bind, duplicate capture and a second
explicit task using the real local checkpoint writer. It does not invoke real
Codex Hooks or GPT. Temporary project cleanup is checked.

## Concurrent persistence and bounded history

A local PostToolUse revision conflict retries only the same event (at most three
append attempts). It rereads the binding and revision before retrying; a changed
binding, timeout, other error, or exhausted retries remains visibly unconfirmed.
Business commands are never retried. Both Hook entrypoints share one 25-second
writer deadline across discovery/read/append retries, inside the configured
30-second Hook limit. Each subprocess gets at most the remaining budget (and at
most 8 seconds); an expired deadline launches no further writer. This is not a
durable local retry queue.

Runner and Server terminal deliveries are deduplicated only across those two
sources when all fields except event ID, source and observation time agree.
Additional outcomes, notes, paths or task state under new IDs remain distinct
evidence. Before acknowledging a cross-source duplicate, the task persists its
incoming ID and normalized content fingerprint in `event_aliases`. Reusing that
ID with changed content is rejected even after reload or event archival. These
metadata-only writes do not increment the fact revision/count; they obey the
existing task and project byte limits. If metadata cannot be saved, no duplicate
acknowledgment is returned.

Task IDs and bindings stay stable when a current segment reaches 128 events or
its byte budget. The writer first syncs an immutable, SHA-256-addressed event
archive, then atomically replaces the task reference. An interrupted rollover
can reuse the identical archive on retry. The writer verifies all referenced
history before accepting new evidence; missing/corrupt/linked files fail closed.
Deduplication and Job/unknown projections include archived events.

`read` returns the current segment in `checkpoint.events`, the full count in
`event_count`, and project-relative archive locations in `history.files`.
`jobs` is bounded to 128 entries with `jobs_total` and `jobs_truncated`; when truncated, consult the current events and history before inferring Job absence.
`checkpoint.unknown_count` covers the entire task, including its history. Use
existing authorized file reads for those archives when older details are needed;
absence from the current segment never means an old operation did not happen.
The JSON and Markdown also retain the archive references for local readers.

There are at most 64 archived segments per task and the existing 2 MiB project
budget still includes the archives. Exhaustion is explicit; no history is deleted
to keep writing. A successor task needs normal explicit task selection. This
removes the 128-event lifetime ceiling, not all storage limits.

All writers/readers (CLI used by Hooks and Runner) must be upgraded together
before rollout. Older binaries reject tasks containing `archives` or `event_aliases`; the first
cross-source duplicate can therefore require the new reader before any archive
rollover. Do not roll back a writer against either format without a compatible
reader. Existing historical duplicate acknowledgments have no reconstructible
alias fingerprint and are not retroactively invented.
This source change does not install or deploy those binaries.

## Upstream integration baseline (2026-09-22)

This downstream integration is carried on upstream commit
`e7dd325d917eec9ed30b740f64d5715b7115c401`. Upstream Job receipt retention
and runtime fixes are used directly. Project handoff storage and the Codex
adapter retain the deployed checkpoint and archival-v2 formats; no historical
event replay or ledger rewrite is required. Both project handoff tools remain
directly available on Adaptive MCP. GPT Actions uses its supported
`call_runtime_tool` route for these two tools to stay within its operation
budget. Their request schemas derive from the canonical typed requests. Runtime result capture preserves the
explicit caller authorization through upstream's consolidated result recorder.

The upstream Workflow Session handoff remains separate from these project-local
checkpoints. Protocol compatibility does not imply local Hook execution receipt
coverage: text-only Hook output continues to produce `unknown`.

## Legacy project-specific configuration

1. Use a reviewed candidate `webcodex` CLI that includes the `handoff` command.
   Supply its **absolute binary path**; an older production executable will not
   provide this command.
2. Explicitly enable one selected project with a `create` JSON request on stdin:
   `webcodex handoff --project /absolute/project --request-stdin`. The request is
   `{"action":"create","task_id":"task-a","title":"Actual task goal"}`.
   Read an existing same-name task before proceeding; never overwrite it.
3. Run `generate_config.py --project /absolute/project --binary /absolute/webcodex`.
   It prints configuration for review. Merge the four hooks into that project's
   existing `.codex/hooks.json` through Codex's normal project-hook trust flow.
   Do not replace existing hooks or turn on a globally disabled feature silently.
4. Reopen the project through the actual Codex entrance being tested. The startup
   hook lists exact task IDs and gives the agent an exact binding command. The
   agent selects the task that matches the user's request; ambiguity needs one
   task choice. The user need not paste a handoff prompt.


## Capacity and maintenance

`status.usage` reports accounted project bytes, task count and `near_limit` at
80% of either existing limit. Hook entry/Stop displays the warning. This is a
warning, not automatic deletion or a promise that saving still has space.
Completed tasks, unknown events, archives, and event aliases remain preserved.
The Server binding limit remains 1024; project limits remain 64 tasks and 2 MiB.
Opening a successor task does not free that shared budget.

Before any capacity recovery, freeze new work on the exact project and inspect
active Jobs, Server pending facts/capture gaps, local sessions, and the current
ledger. Preserve a verified complete copy of JSON, Markdown, referenced archives,
and task/binding identities. A future cold-storage retirement operation must
atomically retain a lookup/tombstone for retired task IDs, reject active or
unknown tasks, and reconcile Server bindings/outbox before releasing capacity.
Do not manually remove tasks/index entries or age out unresolved evidence. This
release provides early warning only; safe task retirement is not implemented.

## Maintenance repository

Maintain one integration branch against a pinned upstream commit. Keep deployment
binaries and machine-specific connection/trust configuration outside Git. Track
upstream and the operator's own remote separately; a local candidate checkout as
`origin` is not a remote backup. Publish only portable code/tests/documentation,
never tokens, private project paths or production snapshots.

### macOS volume identity and legacy checkpoints

New task creation writes `handoff/.volume-anchor.json`. It pins the opened
volume UUID, canonical directory path and inode to the existing checkpoint
fingerprint; a remount may change `st_dev` without invalidating the project.
A copied/replaced directory or another volume still fails closed. Task files,
archives, unknown results and source bindings retain their original identity.

Legacy records without an anchor are never silently adopted after a device
change. A local operator who has verified the exact original directory may use
`webcodex handoff --project <absolute-root> --request-stdin` with
`{"action":"anchor_identity","expected_index_sha256":"<reviewed SHA-256 of handoff/index.json>","confirm":false}`
for review, then the same request with `confirm:true`. The confirmed operation
checks the index digest, canonical path, inode and all referenced task/archive
records under the existing lock, and atomically creates the anchor without
rewriting history. It cannot recover a moved/replaced directory, and is not
exposed through MCP/Runner. Keep a private backup before repairing historical
metadata. A legacy record has no historical volume UUID; this one-time operator
confirmation supplies that missing provenance and must not be automated merely
because an identity check failed. Normal reads never create an anchor.
