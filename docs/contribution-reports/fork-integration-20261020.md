# Fork integration validation — 2026-10-20

This is a historical validation record for a development integration candidate,
not release, installation, or deployment acceptance.

## Source identity and scope

- Upstream snapshot: `f73e99cc1532bdf88dba12191f1835372dbb2377`
- Fork main at start: `929b9e50122b65c7df94cfb4973037ad235a89c3`
- Initial published code commit: `7ae5cac8b5cf37cb69f320c11dfcfe35d8a03a31`
- Initial reviewed/tested Rust integration tree: `1a24de35258996b64b7d95f253de9cc9204843df`
- Python compatibility commit: `25bb10cc1bcd567f35f7339cd05b02ffa72b8117`
- Final reviewed/tested source tree before this report: `34dcbc718965ade5b38d4d58c961c5267a1aba3b`
- Upstream main was rechecked after validation started and still matched the snapshot

Fork main is an ancestor 632 commits behind the upstream snapshot. This PR
intentionally integrates that development history, rather than claiming a small
backport or compatibility with an uninspected installation. The additional fork
source delta covers twelve files.

The snapshot includes upstream MCP command-error diagnostics, execution/admission
fences, job discovery/recovery, and attachment provenance/SSRF improvements. The
fork-specific delta adapts [attachment diagnostics PR 1010](https://github.com/yyjeqhc/webcodex/pull/1010)
and [process fixture PR 1087](https://github.com/yyjeqhc/webcodex/pull/1087) to current
source while retaining [PR 1096](https://github.com/yyjeqhc/webcodex/pull/1096)'s
unique fixture paths, atomic publication, and ordinary startup allowance.

Attachment diagnostics contain fixed failure classifications, bounded HTTP
status/address categories, and canonical request UUIDs. Reference guidance requires
confirmed import and matching destination metadata before a document link.
Process fixtures capture group identity before shell initialization and add a
deadline-before-publication regression; post-capture checks are observational.
Permission defaults and existing provenance-specific address admission were not
changed. Redirect rejection, address pinning, streaming bounds, and uncertain-upload
handling remain in place.

## Executed checks

Environment: isolated Linux x86-64 cloud workspace, Rust/Cargo 1.99.1, Python 3.12.14, Node 24.19.0. No real
credentials, paid models, user applications, or production services were used.
Counts below overlap between focused filters and the full package run; do not add
them together as a unique test count.

| Check | Result |
| --- | --- |
| `cargo test --locked -p webcodex --lib conversation_import` | 21 passed |
| `cargo test --locked -p webcodex --lib mcp::tests::file_import` | 11 passed |
| `cargo test --locked -p webcodex --lib import_http_tests` | 12 passed |
| `cargo test --locked -p webcodex-environment --lib process::tests -- --test-threads=1` | 4 passed |
| `node --test src/mcp_tests/*.test.mjs` | 582 passed |
| `python3 scripts/check_builtin_guidance_contract.py` | Passed |
| `python3 scripts/tests/test_runner_observability_contract.py` | 4 passed |
| Python release-tooling suite within `bash scripts/release_check.sh --static-only` | 814 run, 5 skipped, no failures |
| `python3 -B -m unittest discover -s integrations/codex -p 'test_*.py' -v` | 94 run, 3 skipped, no failures |
| `python3 -B -m unittest discover -s integrations/model_gateway/tests -p 'test_*.py' -v` | 22 passed; mock adapters only |
| `python3 scripts/check_production_warnings.py` | Passed; dogfood profile, zero workspace warnings |
| `cargo fmt --all -- --check` | Passed |
| `python3 scripts/check_markdown_links.py` | Passed |
| `git diff --check` | Passed |
| `cargo test --locked -p webcodex` | Library: 3613 passed, 1 failed, 11 ignored; exit 101 |
| `cargo check --locked --workspace --all-targets` | Passed; one existing test-only deprecation warning |

The attachment checks cover public-only remote provenance, the existing narrow
loopback/OpenAI RFC2544 exception, mixed-address rejection, pinned DNS, trace
sanitization, bounded failure events, HTTP/body failures, and partial import
results. The process checks include timeout/output limits, stdin EOF and both
output pipes, whole-group observation, and delayed shell publication.

The all-targets check emits one deprecation warning for `Atomic::fetch_update` in
unchanged `crates/webcodex-runner-registry/src/tests/job_receipts.rs:33`. The separate
production-only dogfood gate has zero workspace warnings.

### Non-passing checks and environment limits

The full Server package run stops in its library stage at
`server_listener::tests::inherited_fd_rejects_non_tcp_listening_stream_without_taking_ownership`.
`UnixListener::bind` returns `PermissionDenied` / `Operation not permitted` at
`src/server_listener.rs:535` in this sandbox. That fixture and implementation
are unchanged from the frozen upstream snapshot. The failure is at fixture setup,
not the assertion under test. Binary/doc-test stages were not reached; the complete
package suite is therefore **not green**. Sandbox restrictions were not weakened.

The static release gate's Python phase passes after the installed toolchain is
included in PATH. Its subsequent npm wrapper self-test fails at
`npm/webcodex/test/self-test.js:775`: expected `clean`, observed `leaked`. The same
self-test fails identically on the unchanged frozen upstream checkout. Its fixture
assumes `npm_config_https_proxy` was absent from the caller environment; this cloud
executor supplies that proxy variable. The required proxy was not removed and the
assertion was not weakened. The entire static release gate is **not green**.
An earlier invocation without the toolchain in PATH failed with missing-Cargo
setup errors; that invocation is not counted as passing evidence.

## Not validated by local workspace checks

- Native Windows/macOS process behavior, Desktop packaging, or installers
- Real Host attachment references through download, import, metadata verification,
  and final document references
- Installed Server/Runner/Desktop version alignment or migration/rollback behavior
- Ignored real-process suites and full workspace test execution
- Deployment, restart, release artifacts, or real provider/model operation

## Initial GitHub CI evidence

[CI run 39389715286](https://github.com/franksong2702/webcodex/actions/runs/39389715286)
for the published code commit is still running. Its
[Linux tooling job](https://github.com/franksong2702/webcodex/actions/runs/39389715286/job/118518011984)
failed on Python 3.14 in two pathological-JSON cases:
`test_driver_receipt_pathological_json_is_a_contract_error` and
`test_manifest_loader_fail_closes_on_pathological_json`. Those Python files were
unchanged by this integration delta. The corresponding local Python 3.12 suite
passed. At 08:05 UTC, that initial run had completed the Linux Runner and workspace-crate,
contract, macOS core, Windows Runner/package, and MCP conformance jobs successfully;
other jobs were still running. This is partial CI evidence for the original code
commit, not a green final-head workflow.

The exact baseline loaders reproduce those failures on Python 3.14.8. A separate
follow-up makes the intended nesting limit explicit: at most 128 nested JSON
containers for case manifests, benchmark driver receipts, and Host-timing
cohort/comparison input. This is a newly explicit admission limit, not a claim of
unchanged behavior for arbitrarily deep metadata. Existing byte caps and original
pathological-input regressions remain. The initial failure link is retained; final
cross-version results are recorded below.

On the final Python source tree, the exact seven CI modules plus Host-timing
tests passed all 296 tests on Python 3.14.8. The complete script test discovery
then ran 819 tests on Python 3.14.8: zero failures/errors, 5 skipped. Python 3.12.14
also ran all 819 tests with zero failures/errors and 5 skipped. These counts include the mixed-container and
negative-prefix regressions added after the intermediate 817-test run.
No Rust files changed after the Rust validation recorded above.

GitHub CI status is tracked on the PR separately; an in-progress workflow is not
passing evidence. This candidate remains a draft until the required review and
acceptance decisions are made.
