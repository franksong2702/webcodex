# Agent efficiency paired evidence

[简体中文](agent-efficiency-upgrade.zh-CN.md)

This procedure and the completed 2026-10-17 Host-policy baseline provide evidence
for [Issue #1159](https://github.com/yyjeqhc/webcodex/issues/1159). The baseline
contains 18 qualified real-model samples in nine pairs; it does not establish a
production inefficiency or complete the parent Issue’s four-stage scope.
The collector is a thin wrapper over `agent_loop_benchmark` sample ownership, fixture oracles,
runtime gates and `agent_loop_report` comparison. Existing Agent Loop evidence
remains usable without the optional efficiency identity fields.

Knowledge/Skill adoption uses a separate opt-in
[acceptance protocol](knowledge-skill-acceptance.md). These cases and their
authorized supplemental attempts do not replace or recount this historical
18-sample baseline.

## Run the same three tasks

Use a checkout whose HEAD is the exact source commit being tested. The runner
reads the case manifest from that commit, uses fresh detached worktrees, and
runs `readonly_review`, `guarded_multi_file_edit`, and
`long_validation_handoff`. Default three pairs per task produce 18 samples,
alternating Direct → Host Code Mode and Host Code Mode → Direct. Pair count is
bounded to 1–10; each driver has the existing 30-minute process-group limit.
Worktrees, receipts and annotations belong to one temporary directory and are
removed on completion or failure. Setup errors also clean the owned directory.

The long-validation task uses published validation options and Server-controlled
synchronous handoff timing. It does not require an unpublished client timing
hint. Both arms must use the same timing policy; an actual pending Job,
independent work before its real completion, and successful observation of that
same Job remain required. Preserve historical prompts, fingerprints and any
approved contract annotation: an omitted `sync_wait_secs` hint does not prove
that an earlier explicit one-second requirement passed. A changed manifest has
a new case fingerprint and must not be mixed with the frozen baseline.

Provide a real live ChatGPT Host driver executable. It must submit each case
prompt to a fresh ChatGPT task/session connected to the sample workspace and
retain the actual WebCodex audit evidence for that task. Direct uses admitted
WebCodex calls directly. Host Code Mode uses the Host's JavaScript orchestration
of admitted WebCodex tools, preserving the same permissions and Job lifecycle.
It must not substitute WebCodex nested `execute_*_code_mode` for the Host lane.
Job follow-up uses the existing outer Job tools. A scripted MCP driver or mock
model can test the collector, but is not real-model evidence.

Before starting, pin the model/configuration record externally: actual model
identifier, Host version, inference settings, task instructions, tool exposure,
permission configuration and relevant Server/Runner build identities. Hash a
stable serialization of that record with SHA-256; pass its exact lowercase
64-hex digest. Keep the safe record with the experiment evidence. Neither this
hash nor a driver claim independently proves which model ran. Do not include
credentials, private instructions, payloads or private reasoning in published
records. The driver must obtain its attestation from the configured run, rather
than copying expected values without checking its configuration.

```sh
python3 scripts/agent_efficiency_benchmark.py \
  --repo . --base-revision "$(git rev-parse HEAD)" \
  --driver-command '/absolute/path/to/live-chatgpt-driver --pinned-config /private/config.json' \
  --model-config-digest '<64-hex SHA-256 of pinned model/config record>' \
  --pairs 3 --output /private/evidence/efficiency.json --strict
```

The driver receives the existing `WEBCODEX_BENCH_*` environment contract:
workspace, case ID, prompt, variant, surface, exact base revision, case
fingerprint and result-receipt path. It must write the existing bounded result
receipt including status, selected audit database/workflow session, correctness
and validation verdicts, and optional repair annotations. It additionally
writes exactly these `efficiency_attestation` fields (values below are
placeholders):

```json
{
  "efficiency_attestation": {
    "model_config_digest": "<pinned 64-hex SHA-256>",
    "base_revision": "<exact 40-hex commit>",
    "case_fingerprint": "<WEBCODEX_BENCH_CASE_FINGERPRINT>",
    "variant": "host_code_mode",
    "surface": "host_code_mode"
  }
}
```

Direct uses `variant=direct,surface=direct`. Missing, extra or mismatched
attestation fields fail the sample without echoing unexpected receipt values.
Receipts are regular files bounded to 64 KiB. Do not copy private model text,
raw tool arguments or payloads into receipts. The runner emits payload-safe
summaries rather than receipts or raw driver stdout/stderr.

`--experimental-nested` adds an isolated comparison group for WebCodex nested
Code Mode, with its own fresh Direct controls (36 samples at three pairs).
Nested surfaces come from the fixed case definitions. It does not replace or
mix with the default Host result. Same model/configuration pinning is required
throughout; if a configuration changes, start a separate experiment.

## Free tool-selection regression

Stage 2 depends on the generic runtime-evidence acceptance work in merged
[PR #1162](https://github.com/yyjeqhc/webcodex/pull/1162), already included in main.
Separately from the fixed three-task, three-pair efficiency suite, the default `tool_selection` experiment
runs four bounded read-only scenarios: `selection_single_read`,
`selection_batch_read`, `selection_cross_tool_review`, and
`selection_compound_source_context`. The last asks the model to locate and explain
match-derived source-context reads, including overlap coalescing, read limits,
byte-budget fallback and zero matches, citing current source and tests. It names
no required tool or sequence. The existing canonical compound tool is
`search_file_context`; separate searches/reads are equally admissible, and
sufficient returned context does not require another read.

```sh
python3 scripts/agent_loop_benchmark.py \
  --experiment tool_selection --repo . --base-revision "$(git rev-parse HEAD)" \
  --driver '/absolute/path/to/live-chatgpt-selection-driver' \
  --samples 3 --output /private/evidence/selection.json --strict
```

Record the manifest at the exact tested commit before running. The default
selection count is four cases × three repetitions here, without forced-lane
pairs; the efficiency collector remains three tasks × three pairs × two lanes.
The repair and Session-recovery selection cases remain explicit opt-ins. See the
[selection protocol](agent-loop-baseline.md#free-tool-selection-experiment).

For all four scenarios, retain the actual final answer and an independent check
against the tested sources or fixture values; repository review also needs
independent Git state. The file oracle establishes fixture eligibility only.
The caller supplies the external correctness verdict: a driver pass declaration,
canonical call count or final fixture alone cannot establish answer correctness.
The harness has no automatic semantic answer verifier. Missing external
correctness stays partial and cannot pass strict; missing canonical Audit
metadata also fails strict and unavailable counts remain null. Both a single
compound call and separate search/read calls can satisfy the selection runtime
contract; that admission check does not prove the answer or identify optimal
tool choice. Existing overlap/byte-budget/zero-match runtime tests and synthetic
Audit regression fixtures validate contracts, not actual model behavior. No live
measurement of the new case or guidance improvement is claimed here.

## Interpret evidence

Strict mode rejects missing cases, groups, pairs or lane samples, nonpass
statuses, missing/mismatched identity attestations, failed fixture oracles,
unproven runtime/case contracts, and noncomparable exact source/case/correctness
pairs. It recomputes acceptance rather than trusting a stored success flag or
sample count. Strict acceptance does not require every optional metric to
exist and does not prove Host cell grouping or independent model identity.

Each sample and qualified pair reports wall time, WebCodex outer calls,
serialized tool-result bytes, repair turns, outer `observe_jobs` calls, and
immediate-observe scheduling metadata. Missing measurements remain null, with
missing/observed counts in paired distributions. Runner wall time includes Host
driver orchestration; outer calls are not model turns; result bytes are not
complete network traffic; immediate observe is not proof of excess observe.
Deltas are candidate minus Direct; p50/p95 are descriptive nearest-rank values,
not confidence intervals or a speedup claim.

Hotspot candidates are ordered by observed invalid-argument/tool-selection
repairs, same-kind serial Window calls, then explicit observe after a delivered
failure. The serial proxy does not prove unnecessary microcalls. Current
payload-safe summaries cannot prove repeated reads of identical content, so
no repeated-read finding is invented. Observe after delivered failure requires
inspection of necessity before proposing a change. Low call counts alone do
not prove success or efficiency. Inspect actual candidate evidence before
proposing a focused tool-contract or guidance change, rerun the same three
pairs at the changed current revision, and keep correctness/runtime gates.
The completed baseline below does not demonstrate a production efficiency gain.
Unit fixtures validate collection and rejection behavior only.

A live ChatGPT attempt on aligned Server/Runner `d54e21b19d26` supplied
`_wc.compact_execution` to `cargo_test`. Envelope validation returned `-32602`
before dispatch; no Job started. Preserve this attempt as incomplete. Unsupported
field errors now list the target's supported `_wc` field names (or `none`) using
the existing allowlist, without echoing argument values. Direct and gateway
regressions verify rejection before Job creation. This feedback change passes
26 focused runtime tests. It was not deployed in the baseline; its real-model recovery and efficiency effect remain unverified.

## Host single-call versus composition policy

If ChatGPT exposes the connector only through `functions.exec`, a cell containing
one WebCodex call is still a Host call. It does not satisfy the original Direct
control. Keep that acceptance item unverified. Select the independent experiment
with `--experiment host_cell_policy`; the default remains `direct_vs_host`.
Do not combine this mode with `--experimental-nested`.

This mode uses `host_single_call` and `host_composition_allowed` policies across
the same three tasks and three alternating pairs (18 samples). Both samples
retain `variant=host_code_mode` and `surface=host_code_mode`. The policy is a
separate field, passed to the driver as `WEBCODEX_BENCH_HOST_CELL_POLICY`.
Composition is permitted, not required: report whether multiple calls actually
occurred together rather than assuming the instruction caused composition.
The paired deltas use `candidate_minus_baseline`, without naming a Direct lane.

Each receipt must include `host_cell_attestation` with exactly `policy`,
`source="caller_ui_attestation"`, `ui_evidence_sha256`,
`complete_tool_call_coverage=true`, and `cells`. Each cell contains only
`cell_id_sha256` and `tool_trace_ids_sha256`. Cell identities and call identities
must be unique; every measured outer tool call must appear exactly once.
The single-call policy requires exactly one WebCodex call per cell. The
composition policy allows one or more. Keep the actual bounded UI evidence
privately for review. A hash alone does not independently prove execution or
JavaScript grouping: the report explicitly retains caller attestation and
`independently_verified=false`. Audit proves canonical calls, not Host cells or
model rounds. Missing or ambiguous UI-to-call association is partial, including
identical concurrent calls that cannot be uniquely distinguished. Never infer
cell groups from Window proximity, request order, or timestamps.

The separate strict gate rejects Direct samples, mixed experiments, missing
matrix entries, changed policies, missing cell evidence, failed runtime or
fixture checks, and incompatible identity/case/source evidence. Existing report
comparison has an explicit Host-policy compatibility rule; summaries are never
rewritten as Direct. Unknown result bytes, repairs, and model rounds remain
unknown. Local synthetic tests establish these contracts, not real model gains.

For a manual bridge, write `task_timing: null` unless independently evidenced UI
task boundaries exist. An omitted field preserves the automated driver's existing
elapsed-time fallback; an explicit null retains unknown task wall time. Manual
copying, waiting and operator review cannot be measured as model task duration.
Audit observed span is a separate proxy and cannot establish overall speedup.
A private JavaScript fingerprint helper needs an isolated real Host read-only
probe before any formal samples; local JavaScript tests alone are insufficient.

## Completed Host-policy baseline: 2026-10-17

The approved alternative to unavailable Direct exposure ran real ChatGPT tasks
under `host_single_call` and `host_composition_allowed`: three tasks × three
pairs × two policies, with all 18 samples and nine pairs independently passing
the unchanged runtime, task and caller-evidence gates. Direct remains unverified;
nested Code Mode was not run. The frozen fixture source was
`29c906b8a624d315992f7a48d6f1a9a28593721d`; the clean, aligned Server/Runner
source was `d54e21b19d26c3852cf4f9abd723e3e5f13353eb`.
The caller attested the ChatGPT UI selection as GPT-6 with extreme reasoning.
The backend model identity was unknown; this is not independent model verification.

Acceptance required full canonical Audit and fixture checks, external task
correctness, and a unique caller UI mapping covering every actual outer call.
The long-validation samples additionally required a real pending Job, an
independent read before its authoritative actual end, and observation of that
same Job reaching terminal exit code 0. Neither a driver pass flag nor final
files alone met these gates. Host cell grouping remains caller-attested,
`independently_verified=false`.

The legacy explicit one-second `sync_wait_secs` setting was unavailable and was
not published. After the first long sample, the user explicitly approved the
Server-default ten-second policy. Original prompts, fingerprints, rejections
and the approval annotation were retained; the one-second requirement is never
claimed to have passed. Ten retired invalid attempts, two unused preparations
and two superseded, invalidated proofs were preserved and excluded. Private
validation facts were retained before cleanup of the exact sample workspaces
and raw artifacts.

Each table cell is **single-call / composition-allowed**. Calls are canonical
WebCodex outer calls, bytes are serialized tool-result bytes, and observes are
outer `observe_jobs` calls. These integers are the corresponding qualified-pair
`baseline` / `candidate` values for `outer_calls.total`,
`results.serialized_tool_result_bytes.total`, and
`efficiency.job_observe_calls`, respectively; pair numbers are one-based.

| Task | Pair | Calls | Result bytes | Job observes | Attested nonempty cells |
| --- | --- | --- | --- | --- | --- |
| `readonly_review` | 1 | 9 / 9 | 163,826 / 208,012 | 0 / 0 | 9 / 6 |
| `readonly_review` | 2 | 13 / 10 | 171,795 / 209,455 | 0 / 0 | 13 / 7 |
| `readonly_review` | 3 | 9 / 9 | 177,812 / 221,575 | 0 / 0 | 9 / 6 |
| `guarded_multi_file_edit` | 1 | 6 / 6 | 25,576 / 25,627 | 0 / 0 | 6 / 5 |
| `guarded_multi_file_edit` | 2 | 6 / 6 | 25,576 / 25,576 | 0 / 0 | 6 / 6 |
| `guarded_multi_file_edit` | 3 | 6 / 6 | 26,613 / 25,464 | 0 / 0 | 6 / 6 |
| `long_validation_handoff` | 1 | 10 / 8 | 91,903 / 84,197 | 2 / 2 | 10 / 8 |
| `long_validation_handoff` | 2 | 7 / 6 | 64,934 / 79,107 | 1 / 1 | 7 / 6 |
| `long_validation_handoff` | 3 | 6 / 6 | 81,267 / 78,373 | 1 / 1 | 6 / 6 |

Task wall time and repair turns are null for every sample. Immediate-observe
counts are zero in both arms of every pair; this alone does not prove optimal
scheduling. Nonempty cell counts are caller-attested, not independently verified. The
caller additionally reported one empty Host cell for read-only pair 1’s
composition arm, read-only pair 2’s single-call arm, and long-validation pairs
2–3’s single-call arms; other empty-cell counts are unknown.

Instrumentation was equal within each pair but changed across pairs. Read-only
pairs 1–2 used `original_v4` receipt guidance; read-only pair 3 and all remaining
pairs used `verbatim-recursion-reminder-v1`. Only long-validation pairs 2–3 used
`cargo-and-receipt-preflight-v2`; all other pairs used `no_dispatch_guard`.
These collection changes are not product gains. The table supports per-pair
descriptions only: no pooled causal claim, speedup or p95 claim is made.

Literal helper-source conformance is false. In guarded-edit pair 3's single-call
arm, an unused `read_files` branch in the `review_changes` cell omitted a field;
in read-only pair 3's single-call arm, cell c09 changed the executed `wcProject`
branch order. All actually executed receipts were mapped exactly, but other
original Host code and whole-source semantic equivalence remain unverified.
The qualified results establish runtime and task receipts, not whole-protocol
source compliance; they do not establish that all trials followed helper code
verbatim. The separate four-case free-selection experiment has no live result
here. The supported-`_wc`-names feedback fix described above was not deployed
for this baseline, and its real-model recovery or efficiency benefit remains
unverified. This baseline contributes evidence to the parent Issue without
closing its remaining stages.
