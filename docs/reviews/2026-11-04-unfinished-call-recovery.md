# Unfinished-call recovery backport validation

Date: 2026-11-04 UTC.

## Scope and provenance

Backport [upstream PR #1344](https://github.com/yyjeqhc/webcodex/pull/1344),
merged as `1fc31bc2b7fd4e457ec38f7c0167d62566743049`, onto the maintained
fork branch `integrate/reviewed-upstream-20261020` at
`998d85dc8a7f46ef9ca1dbac49933a7638b88ca8`.

The production patch is unchanged from upstream. It projects unresolved
mutating or shell-like call starts across instruction boundaries, requires an
exact later terminal event, and prioritizes reconciliation without executing
or replaying anything. Incomplete retained history is reported explicitly.
No persistence format, authorization, Job lifecycle, dependency or deployment
change is included.

The fork still uses JSON Session persistence. The original SQLite-named async
restore test is therefore adapted to a synchronous ledger-named test using
the existing `flush_persistence()` API. It flushes and drops the original
store, reopens the same ledger, resumes the exact Session, verifies the old
unfinished call still blocks continuation, then verifies its matching finish
clears the uncertainty. This is clean persistence/reload coverage, not a
crash or power-loss durability claim.

## Frozen source identity

- Production file Git blob: `d0f6fac4cd80b7468dd2ab941bc8dd97903959fd`.
- Regression file Git blob: `a1354140d7d3a05e065bd42a9caac3379e79dddf`.
- Two Rust files: 376 insertions, 1 deletion.
- These source blobs were unchanged throughout final validation.

## Local validation

Environment: isolated Linux x86_64 cloud workspace, official Rust
`1.99.1 (58cf8f9c3 2026-10-13)` and Cargo
`1.99.1 (5f94df478 2026-08-27)`. Toolchain paths were isolated from global
shell configuration. Cargo used the checked-in lockfile.

| Check | Result |
| --- | --- |
| New ledger reload regression on the unchanged base plus candidate tests | Expected red: 0 passed, 1 failed; exit 101. Actual status was `in_progress`, expected `blocked`. |
| `cargo test --locked -p webcodex-workflow-session --lib` on candidate, fresh target directory | 305 passed, 0 failed, 10 existing ignored. |
| `cargo test --locked -p webcodex-workflow-session --lib continuation_tests` on candidate | 42 passed, 0 failed. |
| `cargo fmt --all -- --check` | Passed. |
| Workspace boundary checker | All 22 workspace packages passed. |
| Workspace boundary checker self-tests | 20 passed. |
| Patch forward/reverse checks and `git diff --check` | Passed. |

An initial candidate test invocation accidentally reused the red-control target
directory without recompiling and returned the baseline's seven failing new
regressions. That run is excluded from acceptance. Rebuilding the candidate in
a separate, empty target directory passed the full package suite without any
source or test-expectation changes. The original test binary lacked the new
helper's symbols; the clean candidate binary contains them. The red-control
and final test binary SHA-256 values differ:

- Red control: `30bfc6c1a0402a85da2caa44c1db927495c25eb852166e0b1c79952070a4c310`.
- Final candidate: `fc7609cff7e57719520b2b97c270dd3afc7f4016c3e156c0c6d39244494df90f`.

Use separate Cargo target directories for these two worktrees.

## Review and acceptance limits

Independent static review found no blocking defect in the final Rust source.
It checked correlation identity, history truncation, read-only/replay-safe
behavior, older fork API compatibility, and the JSON restore test adaptation.

The tests cover implicit and different Projects, unbound Sessions, call and
logical-role identity, read-only interruptions, accepted asynchronous Jobs,
history truncation, and restoration across a new instruction. Missing call IDs,
duplicate matching finishes, and wrong logical-invocation IDs are handled in
production but do not have dedicated new test cases in this backport.

This is not a full Server integration, native Windows/macOS/ARM64, real Host,
or deployed Server/Runner acceptance result. Exact-head fork CI remains a
separate merge gate. No service restart, release, or deployment is included.
