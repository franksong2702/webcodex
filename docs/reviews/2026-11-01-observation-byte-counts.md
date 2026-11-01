# Observation returned-byte backport

## Source and scope

- Maintenance base: `998d85dc8a7f46ef9ca1dbac49933a7638b88ca8`
  (`integrate/reviewed-upstream-20261020`).
- Upstream: [PR #1332](https://github.com/yyjeqhc/webcodex/pull/1332),
  commit `1393308e76bee6c8b8f4eb5687b166a00d8faae5`.
- Production change is the same two additive output fields as upstream:
  `stdout_returned_bytes` and `stderr_returned_bytes` describe the actual
  returned UTF-8 fragments, not cumulative logs or serialized JSON.
- The existing observation metrics consumer already reads these fields and
  previously fell back to zero. No execution, persistence, permission, or
  recovery behavior is changed.
- The upstream regression test is retained. Its newer `runner_job_update`
  fixture helper is expanded into the equivalent explicit fields because this
  maintenance branch predates that helper. Assertions are unchanged.

## Validation

Cloud Linux x86_64, official Rust/Cargo 1.99.1; no deployment performed.

- `cargo fmt --all -- --check`: passed.
- Focused new regression: 1 passed.
- `cargo test --locked -p webcodex --lib observe_jobs`: 71 passed.
- Red control: removing only the two producer fields makes the new regression
  fail (`None` versus `Some(18)`, exit 101). The fields were restored afterward.
- Workspace boundary self-test: 20 passed; all 22 workspace packages satisfy
  the dependency policy.
- Build identity and Debian lifecycle Python fixtures: 47 passed.
- Runner observability contract fixtures: 4 passed.
- Test inventory self-test: 2 passed.
- CI test-selection/cancellation and macOS signing/release-evidence fixtures:
  27 passed. These are synthetic contract tests, not native macOS acceptance.
- `git diff --check`: passed.

The first unadapted upstream test did not compile because the newer fixture
helper was absent; this was corrected as described above. Windows/macOS/ARM64,
real ChatGPT Host behavior, production binaries, and deployed Server/Runner
identity have not been verified by these local tests. GitHub CI is evaluated
separately on the exact submitted commit before merge.
