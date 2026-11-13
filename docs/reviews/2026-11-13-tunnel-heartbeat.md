# Tunnel heartbeat recovery backport — 2026-11-13

## Provenance and scope

Backport upstream [#1411](https://github.com/yyjeqhc/webcodex/pull/1411),
commit `6d50934b451c9a524cf9077dbc67656c2a8e5129`, unchanged onto maintained
`integrate/reviewed-upstream-20261020` at `8340dd0fc9192c2a0cc594e0d754ead83578a607`.
The reconstructed baseline tree is exactly `cbeeb57cdcc04aaab19830378d241e6b34825d09`.
The upstream six-file patch applies without adaptation. Existing fork diagnostics,
process regressions, full-history recovery and Windows path fixes are retained.

Heartbeat persistence failure no longer terminates the owned Tunnel task. It records
the diagnostic and retries at the normal cadence. Initial publication remains a
launch prerequisite. File validation, private ACL, nonblocking locking, seven-second
saved-observation expiry, shutdown and task-failure semantics remain unchanged.

## Actual validation

- `cargo fmt --all -- --check`: passed.
- `python3 scripts/check_markdown_links.py`: 254 files, 1081 local links, zero missing
  before adding this report; final report is checked again before publication.
- `python3 -m unittest scripts.tests.test_ci_contract_ownership scripts.tests.test_ci_path_risk`:
  43 tests passed; independent reviewer reran these successfully.
- `git diff --check`: passed.
- Independent static review found no blocking concern.
- `cargo test --locked --offline -p webcodex-environment --lib tunnel::health_tests`:
  exit 101, required `atomic-waker v1.1.2` was not cached.
- Online retry with the same locked dependencies: dependency download rejected with
  HTTP 403 by the cloud network policy. No Rust test execution is claimed.

Exact-head fork CI is required before merge. This draft preserves the candidate and
lets normal CI validate it; no skipped check is treated as native acceptance.
No real Host, Windows/macOS, deployed Server/Runner or restart acceptance is claimed.
No deployment, release, credentials, permissions, proxy settings or service restart.

### First exact-head CI

[Run 43354889474](https://github.com/franksong2702/webcodex/actions/runs/43354889474)
on `9bc6de5119d01a4153050638bd4ad2702c80742f` ran the Linux Server, Runner and
workspace-crate suites successfully. Windows core executed the new contention /
expiry test (1 passed) and Server heartbeat tests (3 passed). This is CI evidence,
not deployed Host acceptance or a successful overall run.

Tooling and contract lanes failed in the unchanged build-identity fixture:
`test_packed_branch_without_reflog_refreshes_and_then_stays_cached` and
`test_tracked_dirty_state_refreshes_at_same_head` each failed for normal and linked
worktrees because a hard-coded Cargo output glob returned zero files. CI installed
Rust 1.100.0, updated November 12. The old local 1.99.1 fixture passes; the original
four failures remain recorded and are not waived.

The follow-up fixture uses Cargo JSON `build-script-executed.out_dir` and the
matching executable artifact instead of guessing package-directory spelling.
It still requires exactly one build script and executable, the same package ID,
one stable output path, unchanged cached-output timestamps, and all original
identity/dirty-state assertions. No production build behavior or gate is removed.
Independent review of the delta and all six build-identity tests passed locally
with Rust/Cargo 1.99.1; Rust 1.100.0 validation remains the new exact-head CI gate.

## Other upstream changes inspected

Upstream main is `3c1419678e9c5f513e1f0fcc24d48ca1cd897f93`; latest stable is
[v0.5.0](https://github.com/yyjeqhc/webcodex/releases/tag/v0.5.0).
Git ancestry comparison reports upstream ahead 158 / behind 8 against maintenance;
this is not a count of missing behaviors because some patches were backported.
Fork main is not evidence of the installed version.

[#1418](https://github.com/yyjeqhc/webcodex/pull/1418) introduces a default-off
loopback proxy path with a DNS-pinning trust tradeoff. It is not enabled or included.
[#1415](https://github.com/yyjeqhc/webcodex/pull/1415) improves project catalog latency
but spans inventory generations, cancellation and eight files; deferred from this
small recovery fix. Existing fork [PR #2](https://github.com/franksong2702/webcodex/pull/2)
remains separate; no duplicate work or close/reopen attempt was made.
