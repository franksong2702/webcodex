# ChatGPT task execution and evidence

[中文](chat-task-loop.zh-CN.md)

`work_on_project` keeps strict selector validation. Invalid combinations explain
the authorized discovery path without echoing rejected selectors or diagnosing
Runner availability: use a known canonical Project/issued `project_ref`, or
`list_projects` when unknown; a path requires its exact `client_id`.
The normal workflow investigates applicable instructions and code, states
observable completion conditions, displays a short plan for substantial work,
and continues authorized execution. The default remains `on_demand`: displaying
a plan does not create a durable Goal. Existing read continuations retain their
exact arguments. Pending/uncertain execution retains the original Job identity;
finish independent work before joining the exact blocking Jobs. Successful
tools, finished Jobs and checked steps do not prove the user's outcome.

## Disposable acceptance and strict benchmark gate

The existing [benchmark](../../scripts/agent_loop_benchmark.py) now accepts all
six `generic_agent_disposable_fixture` cases from its case manifest. Each sample
gets an ordinary fresh temporary directory rather than a repository checkout;
the source revision still pins the manifest and runtime evidence rules. The
shared [fixture implementation](../../scripts/e2e_generic_agent_ws.py) supplies
bounded final-file oracles. The Host driver must apply the supplied fixed
locale/timezone/Python environment to commands executed through WebCodex.

In addition to the existing driver contract, generic samples expose
`WEBCODEX_BENCH_TARGET`, `WEBCODEX_BENCH_WORKSPACE`,
`WEBCODEX_BENCH_FIXTURE_ENVIRONMENT` (JSON child environment),
`WEBCODEX_BENCH_FIXTURE_COMMAND` (the prescribed failure-pressure, pending-EOF,
conflict-copy or CSV-conversion Python script), and `WEBCODEX_BENCH_FIXTURE_COORDINATION` (outside the editable Project).
For the stale-read case the driver signals `first-read` after retaining the
exact read receipt, waits for `external-written`, attempts the stale fenced
edit, signals `stale-rejected` only after rejection, then waits for
`rejection-checked` before rereading and completing. The external writer uses
one verified regular-file descriptor and never follows a swapped symlink.
These signals coordinate the fixture; they are not runtime evidence of tool
selection or permission.

Use `--strict` with explicit `--case-id` selections and `--pairs` (forced lanes)
or `--experiment tool_selection --samples`. Exit zero requires the exact
requested sample matrix, passing task and required validation verdicts,
runtime-backed lane evidence and every available file oracle. Missing cases,
`partial`, `unsupported` and missing required evidence fail this gate. Driver
annotations alone cannot prove execution.

All six generic cases require both the independent fixture oracle and
case-specific runtime proof from the separate
[verifier](../../scripts/agent_temporal_evidence.py). A bootstrap-only audit,
correct final files or a driver's declared pass cannot establish execution.
Ordinary reports still read metadata only. Missing/unprovable evidence remains
`partial`; a captured contradictory outcome fails.

For every generic case the benchmark creates a private, case/base/fingerprint-
and fixture-identity-bound `WEBCODEX_BENCH_TEMPORAL_TRACE_ROOT` outside the
editable Project. The driver must use it as the **disposable test Server's**
full trace directory and provide its audit DB plus canonical
`workflow_session_id` (not an opaque Session ref). Bootstrap with
`work_on_project(client_id=..., path=WEBCODEX_BENCH_WORKSPACE)` in ordinary
checkout mode. The verifier binds the actual successful bootstrap to this root,
its returned Session and resolved Project, and the recorded case operations.
Managed-worktree mode, foreign cwd/default cwd/resource and an unproved
registered-Project alias cannot establish this binding. A registered Project
can still be entered through the explicit path form. Record all relevant model
calls with authorized `_wc.record`; stop/drain owned test services before
returning the receipt. Never enable this capture on a shared service or put
credential provisioning through model tools.

Mixed-file proof verifies three actual artifact-transfer path pairs, byte counts
and hashes, plus the supplied conflict-preserving note script or an applied
structured create for `sorted/note-2.txt`. CSV proof verifies the supplied
conversion script or applied structured creates of the two exact outputs,
followed by actual finish receipts whose hashes match independently read
fixture bytes and whose task outcome establishes nonblocking completion.
An arbitrary/no-op script, pending command, dry-run edit or tool count cannot
substitute for these operations. Additional verification scripts must each prove
terminal success and precede the final CSV finish; duplicate controlled mutations
do not qualify. Explicit nonblocking `pass`/`warn` outcomes can establish CSV
completion; `fail`/blocking cannot, and missing outcome fields remain `partial`.
A baseline without output-receipt support remains readable but cannot qualify
this CSV proof. The four temporal cases
retain their actual command, Job, stale-revision and blocking-closeout checks
and serial-order fences. Independent file-transfer calls may overlap. CSV
closeout must follow every recorded task operation except the canonical
`check_workspace_hygiene` observer: its PureRead/project:read contract permits
post-finish diagnostics. That call remains captured and subject to the same
root/Session/Project checks. This exception does not allow post-finish execution,
edits, a second finish or arbitrary observers; outcome and output-hash rules stay
in force.

The verifier checks private regular files, trace UUIDs, compressed/raw bounds
and SHA-256 indexes; correlates canonical Audit outcomes and exact scope;
rejects unrecorded runtime calls and ambiguous temporal ordering; and opens only
selected effective arguments and final MCP responses. Schema-2 proof includes only
closed checks/availability reasons and a coordinator-owned fixture identity
hash (canonical path plus directory device/inode, not a content-freshness
claim). It must match that sample's oracle identity. Paired samples have
independent roots and do not need identical fixture identities. Old schema-1
results remain readable, but do not receive new strict acceptance automatically.
The benchmark removes its owned capture directory after each sample, including
unsuccessful samples. Capture hashes establish local integrity, not independent
Host attestation. Aggregate nested Code Mode counts alone do not establish
individual case arguments/results and remain insufficient for generic strict
acceptance; this verifier does not add a nested-child payload decoder.

An additional `read_session_discussion_summary` call remains covered by the
Audit, scope and ordering checks. Its captured arguments must select the exact
recorded Session, or a short ref mapped to that Session by a prior successful
bootstrap. It is a Session observer, so no Project field or discussion response
is required; the verifier does not open its discussion body. Other calls retain
the normal Project and result checks.

Prepared Python commands must have the exact expected syntax tree, so an
expanded loop, quoting or final newline change does not invalidate execution
evidence. Extra or changed statements and comments (including encoding cookies)
are rejected. This check never executes captured source and does not replace
the required real exit statuses, diagnostics, ordering or dispatch counts.

Use `--candidate host_code_mode` for Direct/Host pairs, keeping the existing
nested `code_mode` default unchanged. All six cases may qualify when both lanes
meet every gate. Nested child evidence without individually captured canonical
results remains incomplete, never reconstructed from outer composition counts.
Host lane qualification proves canonical runtime calls, not one JavaScript cell
or exact model turns. Use the fixed supplied failure/repair scripts. For pending
independent work use `from pathlib import Path` followed by
`Path('independent.txt').write_text('independent work completed')`, or one exact
`edit_project_files` create request for that file/content, before releasing EOF.

The deterministic real Server/Runner smoke checks the verifier against actual
execution and remains separate from proof of ChatGPT choosing those actions.

```bash
python3 -m unittest scripts.tests.test_agent_loop_report scripts.tests.test_agent_loop_benchmark scripts.tests.test_generic_agent_acceptance
cargo build --locked --profile dogfood -j 2 -p webcodex --bin webcodex-server -p webcodex-runner --bin webcodex-runner
python3 scripts/e2e_generic_agent_ws.py --profile upgraded --source-version ACTUAL_SOURCE_ID --report /tmp/generic-agent-acceptance.json
python3 -m unittest scripts.tests.test_agent_temporal_evidence
python3 scripts/e2e_agent_temporal_evidence_ws.py --bin-dir target/dogfood --source-revision EXACT_RUNTIME_SOURCE_COMMIT --output /tmp/temporal-acceptance.json
```

## ChatGPT Host acceptance

Use only an isolated disposable Project and authorized Runner. Ask ChatGPT:

> Inspect this fixture, explain a short plan, fix `add(a,b)` to return a+b,
> run the supplied failing test, diagnose and repair it, rerun validation,
> review the actual diff and report the result. Continue without routine
> confirmation. Never claim validation you did not observe.

Expected: a visible plan followed by investigation, a revision-fenced edit,
observed failure and repair, passing rerun, review and evidence-based delivery.
Repeat with a truncated file read and one long Job plus independent file work:
the exact read continuation should be followed, the Job started once and joined
after independent work. Resume the exact Session in another chat and verify
recovered facts against current source. For an invalid selector, expect rejection
and authorized discovery, not a fabricated offline diagnosis. Withhold an output
artifact or validation evidence and expect an honest incomplete/unproven result.
These scenarios require actual Host observation and remain separate from local
transport and simulated-driver tests.
