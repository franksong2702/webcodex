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
