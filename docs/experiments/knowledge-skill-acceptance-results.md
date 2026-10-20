# Project knowledge and Skill acceptance results

[简体中文](knowledge-skill-acceptance-results.zh-CN.md) · [Protocol](knowledge-skill-acceptance.md)

This historical report covers user-assisted ChatGPT Web attempts collected on
2026-10-19 for [Issue #1159](https://github.com/yyjeqhc/webcodex/issues/1159).
The measurement scope is complete: each frozen case has an attributable outcome,
including failures. The selected per-case classification has four answer failures
(two citation failures and two without an observable final answer) and two passes,
one assisted. This is not a new collector result or a comparable success-rate
denominator. It does not mean that all six tasks passed or establish production
success rate, model speedup, or release readiness.

## Preserved collection cohorts

| Cohort | Source revision | Actual attempts and original results | Protocol/configuration |
| --- | --- | --- | --- |
| First collection | `5bdbaae4` | Six: 0 pass, 1 fail, 5 partial | Earlier Session-ID wording; Apps enabled |
| Supplement 1 | `3e1d7f41` | Two: 0 pass, 1 fail, 1 partial; four stopped before execution | Session ID separated from JSON; common pause wording still ambiguous; Apps enabled |
| Supplement 2 | `7533876f` | Two: 0 pass, 1 fail, 1 partial; two stopped before execution | Pauses restricted to update cases; Apps enabled |
| Supplement 3 | `7bfe3feb` | Three: 1 pass, 1 fail, 1 partial | Pauses restricted to update cases; `mcp_apps_enabled=false` |
| Supplement 4 | `7bfe3feb` | One: 1 pass, assisted | Apps disabled; distinct configuration digest records the user-reported connection refresh and closing older test dialogs |

There were 14 actual attempts (6 + 2 + 2 + 3 + 1) and six unexecuted slots.
Unexecuted entries are not model attempts. Original failed and partial attempts
remain part of the record. Sources and configuration digests differ between
cohorts: these are separately identified observations, not interchangeable
retries or one comparable success-rate denominator. Disabling Apps changes tool
exposure and presentation. It does not prove that Apps caused a Host failure or
that this setting improves model performance. A Host reply failure was still
reported with Apps disabled. Supplements 3 and 4 use the same clean build and
Apps setting, but their configuration digests differ because the later record
includes the connection refresh. Browser origin remains unproven. All first
four collectors exited strict validation nonzero; Supplement 4 passed its own
one-case strict validation. Earlier strict results remain unchanged.

## Outcomes by frozen case

“Partial” means required evidence is unavailable; “fail” means an observed
acceptance condition failed. Source retrieval, resource adoption, answer
correctness, and evidence completeness are separate observations.

| Case | First attempt | Supplemental outcome | Resource adoption | Answer correctness | Evidence limit |
| --- | --- | --- | --- | --- | --- |
| Identifier implementation | Partial | Supplement 1: original partial; historical classification fails citation check after repaired coverage | First: ordinary reads; supplement: Plugin | Supplement facts correct; additional distractor citation fails frozen check | Parser-rejection classification repaired in separate analysis; original result unchanged |
| Audit procedure | Partial; no final answer was displayed/reported | Supplement 1: fail | Skill used in both | Supplement facts correct; Skill-relative citation fails project-relative path check | Coverage complete; unnecessary non-update pause required one recorded follow-up |
| Chinese knowledge paraphrase | Partial | Supplement 2: fail; no final answer was displayed/reported | First: required Plugin path absent; supplement: successful Plugin search/read | Supplement source facts obtained; no final answer to accept | Supplement coverage and binding complete; Host delivery/render cause unknown |
| Knowledge source update | Fail; checkpoint not admitted | Supplement 2: partial, no update; Supplement 3: pass | Supplement 2 initial Plugin read succeeded; Supplement 3 old/new Plugin reads observed | Supplement 3 current facts and citations pass | Supplement 2 unattributed App polling blocked coverage; no advance. Supplement 3 independent oracle and all scoped checks pass |
| Skill definition and reference | Partial | Supplement 3: fail; no final answer displayed/reported; null answer submitted | First: Skill body loaded, reference read through ordinary file API; supplement: definition and reference read through Skill APIs | First facts/citations correct; extra Session key fails format; supplement has no displayed final answer | Supplement coverage/binding and required hash/revision source checks complete; original independent oracle passed |
| Skill definition update | Partial; no final answer was displayed/reported | Supplement 3: partial; Supplement 4: assisted pass | Actual revision-bound Skill reads before and after the definition change; one operator feedback message in each supplement | Supplement 4 current facts and citations pass | Supplement 3 remains partial. Supplement 4: 14 canonical calls, no adapter rejections, complete coverage/binding and independent oracle |

The first collection's three observed JSON answers violated the exact answer
contract. Earlier operator wording requested the canonical Session ID “with your
final JSON,” while the case described an object “containing” facts and sources.
The evaluator required exactly two keys. Extra Session keys are therefore a
prompt-induced format confound as well as frozen rubric failures; they must not
be attributed solely to model behavior. Later wording requests Session identity
separately. Both Supplement 1 answers had correct facts but inadmissible
citations; neither the rubric nor the saved answers was relaxed. Its common
pause prefix also caused non-update pauses; the recorded operator follow-ups
remain interventions. Version 3 makes the update-only pause condition explicit.

## What the evidence establishes

The first six original knowledge verdicts were unavailable. Independent original
fixture oracles passed exact inventory, source bytes, tracked files, Git head,
and index for five cases. The first source-update case instead records
coordination failure; do not infer an integrity pass for it. Later historical
source comparisons inherit the recorded oracle and matching capture marker.
They do not recreate deleted fixture identities, rerun live oracles, or overwrite
original results.

Demonstrated evaluator repairs include canonical numbered-file matching,
separate binding for valid Session-only messages, and narrowly recognizing a
fully captured Plugin parser rejection. The last requires intact payloads,
matching audited Window/principal, a known pre-provider validation error, no
Session linkage, and no runtime execution phases. It contributes neither a
Session-linked execution nor source evidence. Generic coverage and unknown,
foreign, corrupt, or runtime-bearing rejection checks remain strict.

Actual Plugin source retrieval succeeded in supplements, including the directed
Chinese case. Three initial missing-Project describes in that attempt failed
before dispatch; the model then supplied the required Project and recovered.
Successful local tool responses establish neither receipt nor rendering in
ChatGPT. Reported “无法加载此回复” errors remain Host observations with unknown root
cause; no model answer was manufactured for them.

The second source-update attempt obtained its required initial knowledge read,
but periodic app-only Workbench observations entered the Server capture. Their
audit principal matched, while Window identity and Workflow Session linkage were
absent. The coordinator did not bypass coverage: no checkpoint was requested,
the source remained unchanged, and no final answer was claimed. Closing older
widgets and changing the next cohort's Apps setting does not retroactively
repair that attempt. Future App-origin observability is a separate diagnostic
need, not grounds for an exemption.

Supplement 3's source-update attempt passed independent verification: 13 canonical
calls and one separately classified adapter rejection. It observed an old-hash
refusal, refreshed the index, searched and read the updated source, and returned
correct current facts and citations. This is acceptance of that scoped case,
not acceptance of the complete six-case protocol.

The same cohort's Skill-read attempt completed definition and reference retrieval
through `load_skill` and `read_skill_file`: six canonical calls, no adapter
rejections, complete coverage/binding, and all required source checks. Its
independent oracle passed, but the user reported a Host reply error and no final
answer was displayed/reported. The submitted null answer therefore fails the
answer check. Apps being disabled did not remove this observed Host failure.

Its Skill-update attempt first read the reference through ordinary file access.
After one recorded operator feedback message, a revision-bound `read_skill_file`
returned the required reference with matching hash and range. This assisted
recovery is not an unassisted resource-choice result. Seven additional requests
without Window identity still blocked strict coverage: two Goal searches
returned HTTP 200 with tool failure (`resource_access_denied`); three Workbench
calls returned HTTP 400 because Apps were disabled; a direct Session-list call
and an App-resource request were also rejected. Cached metadata or browser origin
is unproven. No exemption was added, no checkpoint advanced, and the definition
remained unchanged; no final answer was displayed/reported and null was submitted.
All three original independent fixture oracles in Supplement 3 passed; the
Skill-update oracle pass does not substitute for missing coverage or update order.

After the user reported a normal connection refresh and closing older test
dialogs, Supplement 4 completed a separately preserved Skill-update attempt on
the same clean build and Apps setting, with a distinct configuration digest.
Its initial reference read used ordinary file access. One operator feedback
message was needed before a revision-bound Skill reference read admitted the
coordinator checkpoint. The coordinator changed the definition; the next actual
`read_skill_file` refused the old revision with `skill_definition_changed`.
The model then loaded the current definition and read its body and reference
under the new definition revision. Final facts and citations were correct.
All independent checks and the oracle passed: 14 canonical calls and no adapter
rejections. This is an assisted pass, not an unassisted discovery result. The
connection refresh is operator-attested; the source of prior browser requests
and any causal effect of refreshing remain unproven.

Recorded local validation comprises 272 Python tests and 47 provider tests.
Disposable integration smokes report zero model samples; they validate runtime
contracts and cannot replace the actual Web attempts. These checks do not alter
any preserved collector verdict.

## Bounded follow-up

The primary supported T03 change is action-specific Plugin argument recovery
guidance: a bound call should explain that Project belongs on describe. A
secondary candidate is canonical project-relative Skill citation paths. These
follow from observed input and citation failures; they do not justify retrieval
tuning, Memory expansion, weaker evidence gates, or a new benchmark. Unknown
Host rendering failures and future App-origin observability are separate
diagnostics. All failed calls, interventions, and original cohorts remain in
the measurement record.

Raw answers, capture payloads, private identities, credentials, and operator
state are excluded. Internal model identity, tokens, cache behavior, model-turn
counts, and comparative timing are unknown and are not estimated here.
