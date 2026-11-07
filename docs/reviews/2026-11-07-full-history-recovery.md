# Full-history recovery backport validation

Date: 2026-11-07 UTC.

## Scope and provenance

This change selects only [upstream PR #1374](https://github.com/yyjeqhc/webcodex/pull/1374),
merge `f855f32fd0741342a567a37e0576a73d341fffcb` and final PR head
`bc8e25d21df5ba7b340b1f14b79dc8ec635bdb8c`, to improve the existing
[fork PR #3](https://github.com/franksong2702/webcodex/pull/3).
The exact patch base is `bda7eb67fc493c501986cb0c344c8d246f672b04`, which
already contains the earlier #1344 backport above maintained branch base
`998d85dc8a7f46ef9ca1dbac49933a7638b88ca8`.
The [earlier validation report](2026-11-04-unfinished-call-recovery.md) is
historical evidence and remains unchanged.

The comparison snapshot freezes upstream main at
`49604f7b8f5f7dc602eccbe225a71949dd3001eb` and stable `v0.5.0` at
`354541eaa729a1c4bb6f35d4add46a95db4fbca4`. This is not a wholesale main or stable
upgrade. Fork-only patches remain in the ancestry; fork PR #2 is unchanged.

## Behavior and fork adaptation

The production patch matches #1374: compute unfinished mutation evidence over
all retained events before slicing the model-facing summary, then consume that
internal fact in continuation projection. A reverse scan requires an exact,
later finish for the same Session, event-resolved Project, tool, call ID,
logical invocation ID, and role. One finish cannot certify two starts;
duplicate finishes or absent/empty call IDs fail closed, and optional identity
fields must match exactly. Read-only interruptions remain
nonblocking, accepted Jobs keep their separate lifecycle, and actual history
eviction still reports incomplete evidence. Nothing executes or replays a call.

The scan remains bounded by retained Session history. It does not enlarge the
summary window or durable retention, create new authority, or change storage
format. The new summary field is not serialized. The fork retains its existing
JSON ledger, not upstream SQLite persistence. The existing JSON reload test is
strengthened to retain the unfinished call beyond the 200-event summary window,
flush and reopen the ledger, and confirm only the matching finish clears the
block. This proves clean reload, not crash or power-loss durability.

Additional assertions check nonserialization, hot/cold projection parity,
reference-summary parity, duplicated starts/finishes, reused identities,
finish ordering, absent/empty call IDs, and wrong Session/tool/logical IDs.
Existing tests retain call/Project/role mismatch and Job lifecycle coverage.

## Cloud validation

Environment: isolated Linux x86_64 cloud checkout, Rust
`1.99.1 (58cf8f9c3 2026-10-13)` and Cargo
`1.99.1 (5f94df478 2026-08-27)`. Explicit isolated `CARGO_HOME`,
`RUSTUP_HOME`, and `PATH` were used with the checked-in lockfile and
`CARGO_BUILD_JOBS=4`. Red and green worktrees used distinct fresh target
directories; no baseline/candidate binary reuse.

- Red control: unchanged `bda7eb67` production plus the new window regressions.
  `cargo test --locked -p webcodex-workflow-session unfinished_mutation_beyond -- --nocapture`
  executed two tests, both failed as expected with exit 101: actual
  `in_progress`, expected `blocked` (316 filtered out).
- Final green: `cargo test --locked -p webcodex-workflow-session`:
  309 passed, 0 failed, 10 existing ignored; doc tests: 0.
- Server constructor/integration compile: `cargo check --locked -p webcodex --tests`:
  passed. This is compile evidence, not Server test execution.
- Independent reviewer reruns with `--offline --locked`:
  `cargo test --offline --locked -p webcodex-workflow-session --lib continuation_tests`
  passed 46 tests; the corresponding `--lib borrowed_projection_tests` filter
  passed 7 tests with 4 existing ignored.
- `cargo fmt --all -- --check`: passed.
- `bash scripts/workspace_boundary_check.sh --self-test`: 20 passed.
- `bash scripts/workspace_boundary_check.sh`: all 22 workspace packages passed.
- `python3 scripts/check_markdown_links.py`: passed.
- `git diff --check`: passed.

## Acceptance limits

The ignored tests remain unexecuted. This change has not received full Server
runtime test execution, real Host/MCP integration, native Windows/macOS/ARM64,
release, or deployed Server/Runner acceptance in this cloud run. Exact-head
remote CI and independent review remain separate gates. No service restart,
release, deployment, or upstream publication is included.
