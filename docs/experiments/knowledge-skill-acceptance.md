# Project knowledge and Skill acceptance

[简体中文](knowledge-skill-acceptance.zh-CN.md)

This opt-in protocol supports the T01/T02 scope of
[Issue #1159](https://github.com/yyjeqhc/webcodex/issues/1159). It extends the
[Agent Loop collector](agent-loop-baseline.md), not the production tool API,
permission model, provider algorithm or Memory. The original selection defaults
and strict gates remain unchanged. Public material contains synthetic facts and
sanitized conclusions; raw Host answers, captures and operator state stay private.
The [historical results](knowledge-skill-acceptance-results.md) retain the initial
attempts, authorized supplements, measured failures and operator interventions.

## Evidence gap

| Existing evidence | What it establishes | What it does not establish | Additional evidence here |
| --- | --- | --- | --- |
| [Efficiency baseline](agent-efficiency-upgrade.md), 18 real-model samples in nine pairs | Correctness-qualified observations of the frozen Host-policy tasks | Knowledge/Skill adoption, production speedup or success rate | Six separate resource-oriented conversations; no reuse of those 18 samples |
| Merged [#1160](https://github.com/yyjeqhc/webcodex/pull/1160), [#1162](https://github.com/yyjeqhc/webcodex/pull/1162), [#1165](https://github.com/yyjeqhc/webcodex/pull/1165) | Existing incremental refresh and collection infrastructure | A model actually discovering and reading current project resources | Reuse the infrastructure and observe actual calls |
| Provider unit tests and disposable MCP/WS smoke | Scope, exact Project binding, traversal, changed/deleted-source exclusion and provider retirement | Host tool choice or model answer quality | Independent factual/citation and resource-path checks |
| Scripted six-case verifier integration | Real Server/Runner/provider, captured result shapes, controlled updates and negative stale reads | Any real-model sample | User-assisted ChatGPT Web execution with captured identities |

## Frozen cases and independent oracle

Prompts live in [`agent_loop_cases.json`](../../scripts/agent_loop_cases.json).
[`agent_knowledge_fixture.py`](../../scripts/agent_knowledge_fixture.py) owns
the independent answer rubric and deterministic Git fixtures. Only the fixture
checkout is exposed to the sample Runner; the evaluator and rubric are outside
its allowed root. Each sample gets its own Project, index cache, Project Skill,
Runner, capture marker and prompt fingerprint. Similar names contain different
facts. The provider cwd must equal that exact fixture root.

| Explicit case ID | Tool-choice policy | Required observation |
| --- | --- | --- |
| `knowledge_identifier` | Free | Correct receipt identifier implementation and source ranges; record Plugin adoption separately |
| `knowledge_procedure` | Free | Current audit order, marker and batch; record Skill adoption separately |
| `knowledge_paraphrase` | Project knowledge resources required, no prescribed function | Relevant ledger facts and sufficient hash-bound excerpts |
| `knowledge_source_update` | Project knowledge resources required | Initial read, coordinator-only source change, current facts and source hash |
| `knowledge_skill_read` | Project Skill required | Definition and referenced resource; loading or discovery followed by reading are both legal |
| `knowledge_skill_update` | Continue verifying the selected Skill | Initial read, changed definition, new definition revision and current resource facts |

Use one fresh ChatGPT Web conversation per case. Search excerpts count when they
actually contain all required facts; no redundant read or optimal tool sequence
is prescribed. Ordinary file reads may pass either free case without proving
Plugin/Skill adoption. The four directed cases fail their resource-path check
when only ordinary files were read. Bootstrap-only or a driver-declared pass
cannot prove a sample. Final JSON must contain exactly `facts` (the requested
`key=value` strings) and `sources` (project-relative path and inclusive line range).
Report malformed or wrong answers as answer-contract failures, without inventing calls.
The Host prompt explicitly asks for the canonical Session ID separately before
the final JSON. Earlier saved prompts asking for the ID "with your final JSON"
are ambiguous about that separation; retain their original answers and rubric
verdicts, and report this prompt confound alongside factual correctness.
The Host protocol makes the existing recorder contract explicit:
bootstrap once before Project/resource discovery, retain the exact Session, and use `_wc.record` for relevant MCP
calls, including calls without a business `session_id`. Recorder metadata must
not be added as extra business selectors to a bound resource call. Operator
pauses and confirmations travel through the same ChatGPT conversation, without
opening UI cards or using Session messages as an operator transport. These
instructions do not prescribe a knowledge/Skill tool name or retrieval order.
Version 3 makes pauses conditional on the two update cases. Earlier v2 samples
can pause unnecessarily because its common prefix requested a checkpoint;
preserve these replies and record any operator clarification separately.
Private `ready.json` records the protocol version and exact prompt SHA-256.
An authorized supplemental collection retains the original attempts and result
file, uses a separate output, and freezes its own source/configuration identity.
The knowledge verifier binds Session-only control messages to their exact
authorized target separately from filesystem work. It still verifies their
recorded Window/principal and returned Session identity; they supply no source
evidence. Generic Project binding and missing-Window rejection remain unchanged.

The update cases pause after the first complete resource read. The coordinator
independently verifies that read in the exact Workflow Session before changing
one admitted file. The Host then continues in the same conversation. For Skill
updates the definition changes, rather than only an ancillary resource. Actual
old-hash/revision refusals are retained as failed calls, not missing capture.
Checkpoint feedback is an operator intervention and must be reported separately;
it never substitutes for the actual required resource reads or proves unassisted recovery.
The report describes whether the model recognized invalidation and how it
recovered; a script's deliberate stale read proves only the runtime guard.

## Run and operate

Build aligned dogfood Server/Runner binaries from a clean, committed source.
The source commit must include the opted-in manifest. Prepare an owner-only
state directory and `model.json` outside the repository, for example:

```json
{
  "host": "chatgpt_web",
  "displayed_model": "operator-observed label",
  "displayed_reasoning": "operator-observed setting",
  "internal_model_id": null,
  "tool_exposure": "dedicated WebCodex connection, frozen source manifest",
  "instructions": "fresh conversation, supplied sample prompt"
}
```

Record the actual displayed configuration; never infer an internal model ID.
The driver hashes this private record and checks binary versions/source hashes.
The result preserves only this digest and bounded build metadata. Neither an
operator declaration nor its digest independently attests a remote model.
Strict acceptance requires identical pinned configuration/build identities.
The optional boolean `mcp_apps_enabled` pins the Server's existing presentation
setting (default `true`). For text/resource acceptance, `false` suppresses App
tools and widget metadata; it does not change knowledge/Skill APIs, permissions
or evidence gates. Record this as a different tool-exposure configuration, not
a comparable retry. Close older test widgets before collecting: their polling
can otherwise enter the same Server capture without a Workflow Session/Window.
Such unattributed calls still block strict acceptance; no UI exception is added.

```sh
python3 scripts/agent_loop_benchmark.py \
  --repo . --base-revision '<exact committed source>' \
  --experiment tool_selection --samples 1 \
  --case-id knowledge_identifier --case-id knowledge_procedure \
  --case-id knowledge_paraphrase --case-id knowledge_source_update \
  --case-id knowledge_skill_read --case-id knowledge_skill_update \
  --driver 'python3 /absolute/checkout/scripts/agent_knowledge_host.py drive --state-dir /private/knowledge-run --bin-dir /absolute/dogfood --model-config /private/knowledge-run/model.json' \
  --output /private/knowledge-run/result.json --strict
```

The driver creates one isolated loopback Server and Runner at a time. A private
`samples/<sample-id>/ready.json` identifies its Project, paths and exact source;
`prompt.txt` is the task to paste into the fresh web conversation. Reuse the
task-owned connection URL/auth database across these sequential samples only.
An operator-provisioned connection may additionally specify `username` alongside
its existing `owner` PAT in private `connection.json`. The driver then enrolls
the sample Runner under that exact account, preserving Project visibility;
the default remains `knowledge-owner`. The operator must independently provision
a current authorized grant. The driver does not renew expired grants, import
token hashes or modify native recovery history. Reusing a protected Tunnel
requires its original URL/header and journal through supported recovery; a
fresh evaluation state directory does not authorize bypassing that history.
Connect through a dedicated test tunnel and test credential using the normal
[MCP connection flow](../MCP.md) and
[native tunnel client](../../crates/webcodex-openai-tunnel/README.md).
With Secure MCP Tunnel, locally forward to the loopback `/mcp` using the
dedicated owner's scoped PAT from private connection state; keep the complete
local authorization header in an owner-only file. ChatGPT selects Tunnel and
No authentication; do not paste the bootstrap credential into ChatGPT.
Alternatively `drive --public-url https://test.example` configures an explicit
HTTPS OAuth origin; normal client provisioning remains an operator step.
No login, connector creation, browser interaction or model execution is automated.

Every relevant tool call must be recorded to the exact canonical Workflow
Session returned by this sample's bootstrap. Never choose the most recent
Session by time. After the model pauses in an update case:

```sh
python3 scripts/agent_knowledge_host.py checkpoint \
  --sample-dir /private/knowledge-run/samples/<sample-id> \
  --session '<canonical Session ID>' --trace-id '<observed successful source read>'
```

Wait for `advanced.json` in the private coordination directory advertised by
`ready.json`; `coordination-failed` means stop and diagnose. Only then notify the
model to continue. Do not edit the fixture by hand. Preserve a failure as a
failure, rather than silently rerunning the sample. At completion save the actual
final JSON answer in a private file, then:

```sh
python3 scripts/agent_knowledge_host.py submit \
  --sample-dir /private/knowledge-run/samples/<sample-id> \
  --session '<canonical Session ID>' --answer-file /private/final-answer.json
```

If the Host displays an error without a final answer, save the operator's exact
observation as private UTF-8 text and use `--host-failure-file /private/failure.txt`
instead of `--answer-file`. This retains a separately labeled operator observation
and submits `answer=null`; it never manufactures model JSON. Obtain the exact
Session from that attempt's bootstrap capture if the Host did not display it.
Local tool success alone does not establish Host receipt/rendering or a model
failure, and incomplete capture or identity remains `partial`.

The driver stops its services, retains bounded private captures, and returns a
candidate receipt. The parent independently verifies evidence before assigning
status. Each driver has the existing 30-minute process-group limit; submission
must arrive within 29 minutes. An interrupted operator run is not a qualified
measurement. Stop only task-owned processes; keep existing experiments intact.

To drain a collection after its active sample, use `stop-after-current` with
`--state-dir`, `--base-revision`, `--model-config` and a bounded `--reason`.
This owner-only request is pinned to that source/configuration. It leaves the
active sample running; subsequent drivers return `unsupported` before starting
any Server, Runner or model session. These unexecuted cases are not model
attempts. Let the parent save its original result, then use `resume-collection`
with the same identity to archive the request before a separate continuation.
Never overwrite the previous output or mix protocol versions without reporting
their separate identities.

## Evidence and limitations

[`agent_knowledge_evidence.py`](../../scripts/agent_knowledge_evidence.py) reuses
bounded compressed capture integrity, canonical audit identity, trace coverage,
and fixture/Session/Project binding checks. It requires actual returned source
bytes, source ranges, current hashes/revisions, factual citations, exact fixture
inventory and coordinator update order. Writes outside the admitted update,
wrong Project, missing capture, stale content and forged receipts cannot pass.
Missing or ambiguous evidence is `partial`; an observed failed acceptance check
is `fail`; unsupported adapters stay `unsupported`. Existing strict failures
remain failures. A failed model attempt with complete attributable evidence is
a valid measurement, even though `--strict` exits nonzero.

An exactly recognized Plugin argument-parser rejection can be fully captured
before Session recording and provider execution. The knowledge checker counts
it separately only with matching audited Window/principal, intact raw/error
payloads, the known validation error, no Session link, and no runtime phases.
It supplies neither a canonical Session call nor source evidence. Unknown,
foreign, corrupt or runtime-bearing traces remain incomplete evidence; generic
trace coverage is unchanged.

Native Plugin captures redact opaque bindings and nested arguments. The checker
therefore combines an observed Project-bound description with returned source
hashes, the exact Session and the coordinator-pinned sole provider. It does not
claim to decode or independently compare a redacted opaque binding. Some Skill
calls have no efficiency telemetry; their actual canonical audit operation and
captured result still prove reads, while absent metrics remain unknown. Full
raw captures and answers remain private; do not publish the collector's whole
output without a separate sanitization check.

Local validation uses:

```sh
python3 -B -m unittest scripts.tests.test_agent_loop_benchmark scripts.tests.test_agent_loop_report scripts.tests.test_agent_efficiency_benchmark scripts.tests.test_agent_temporal_evidence scripts.tests.test_agent_knowledge_fixture scripts.tests.test_agent_knowledge_evidence scripts.tests.test_agent_knowledge_benchmark
python3 -B -m unittest discover -s plugins/project-knowledge -p 'test_*.py'
python3 -B scripts/e2e_project_knowledge_ws.py --bin-dir /absolute/dogfood
python3 -B scripts/e2e_agent_knowledge_ws.py --bin-dir /absolute/dogfood --source-revision '<runtime source commit>'
```

The last command deliberately supplies scripted answers and reports
`model_samples: 0`. A real report separately lists each of six attempts, factual
correctness, resource adoption, evidence completeness, source/configuration
identity and observed recovery. Missing tokens, cache hits, model turns and
timing remain unknown. Six single attempts establish neither production success
rates nor speedup. Attribute the smallest demonstrated next improvement to
Issue #1159; retrieval tuning and Memory expansion remain outside this protocol.
