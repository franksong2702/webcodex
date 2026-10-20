# Generic Agent browser acceptance

[简体中文](agent-generic-web-acceptance.zh-CN.md)

These observations support stage 1 of
[Issue #1159](https://github.com/yyjeqhc/webcodex/issues/1159). They are individual
user-assisted ChatGPT Web trials, not paired efficiency measurements or evidence
of unattended continuation.

## Environment and evidence

On 2026-10-16, a dedicated ChatGPT connection used a new OpenAI Secure MCP
Tunnel, an isolated managed user, Runner and disposable Projects. Server and
Runner reported clean build `cff2fe3da102`, version 0.5.0, with exact build and
source alignment. The user kept the same displayed reasoning setting, “极高”.
The exact model identifier and browser version were unavailable; no guessed
model identity is asserted.

The operator prepared deterministic fixtures before model execution, inspected
canonical Audit/trace metadata, selected the exact recorded Session, and used
the independent verifier and final filesystem oracles. Full captures were
enabled only on this disposable service. Private Session IDs, machine paths,
credentials and raw payloads are not published here. Ordinary reports continue
to read metadata only.

| Case | Actual observation | Independent final-state evidence |
| --- | --- | --- |
| Failure and repair | Two actual executions, exit 7 then 0; diagnostic and final sentinel retained | No fixture files created |
| Pending and independent join | One original Job; independent create before stdin close; one readiness join and terminal observation, exit 0 | Exact independent file bytes |
| Missing output | One explicit finish request; missing=1, verified=0, blocking fail | Declared CSV remains absent |
| Stale revision | Old revision rejected; operator checks unchanged bytes before fresh read and one applied edit | External marker preserved exactly once |
| Mixed files | Three artifact transfers plus one applied text create, preserving existing destination | Four unchanged inputs, five exact targets, binary signatures and matching hashes |
| Encoded CSV | Controlled UTF-8/UTF-16 conversion, exit 0; two verified output receipts | UTF-8/LF output, four rows totaling 17, matching JSON and unchanged input hashes |

The missing-output trial passes a protection check; it does not deliver the
missing user artifact. CSV completion remains **nonblocking `warn`**, including
dirty-workspace/hygiene warnings and `validation_inconclusive` /
`source_unproven`. Independent byte checks do not erase the runtime's warning
about validation-source stability.

## Reproduced verifier corrections

The failure/repair trace initially failed byte-exact command matching after
harmless Host formatting. The same captured executions passed `32562ad2`'s
exact Python syntax-tree check. Its bounded before/after facts were retained
and raw capture deleted. This is schema-1 evidence; later schema-2 verification
cannot be replayed from that deleted capture. Supplemental Audit/registered
Project path checks establish its observed fixture association, without
claiming a retrospectively captured directory identity.

Self-check also reproduced a bootstrap-only false acceptance for mixed files
and CSV with driver-written correct outputs. Schema-2 now requires actual
case operations and fixture/Session/Project binding for all six; the no-mock
regression rejects both lanes. Local MCP/WS tests exercise all six cases and
the structured CSV alternative. These scripted tests are runtime verification,
not additional real-model samples.

The real CSV Session included a read-only `check_workspace_hygiene` after
finish. The verifier previously rejected this ordering. The correction retains
the whole Session and allows only this canonical PureRead diagnostic after
finish; post-finish execution, edits and repeated finish remain rejected.

See the [capture and strict acceptance contract](../implementation/chat-task-loop.md)
for bounds, privacy, incomplete evidence and supported execution paths. These
observations do not establish general model reliability, a speedup, background
browser scheduling guarantees or a production deployment.
