# Windows admin Project path backport validation

## Scope and immutable sources

This candidate backports [upstream PR #1413](https://github.com/yyjeqhc/webcodex/pull/1413),
merge commit `991a7c3e0943131bac993c290de5d136205bb6d4`, onto the maintained fork
branch `integrate/reviewed-upstream-20261020` at
`3ca34f673f6e169c376c7e279eabd62a597ba666`.
The five upstream files applied without source adaptations: the admin adapter
uses the existing cross-platform path validator, retains the 4096-byte limit,
and adds HTTP regressions and matching English/Chinese Runner documentation.
The test fixture retains its temporary database directory for its service lifetime.

The Runner still owns native path interpretation, canonicalization and allowed
roots. Authentication, same-origin checks, strict JSON admission and downstream
authorization are unchanged. This is not a native filesystem permission change.
Existing fork diagnostics, process fixtures and Session recovery patches remain
in the base. Fork `main` and any installed deployment are separate states.

The five-file patch generated with `git diff --cached --binary` before this
report has SHA-256
`574dd4d6d14bbf2ee132eb03e851a9ff72953e6fe2b114229e6cec7c35370143`.

## Local validation

Validation used an isolated Linux cloud checkout and existing isolated official
Rust/Cargo 1.99.1, locked dependencies and a new dedicated build directory.

- Fail-first control: unchanged production base plus upstream test/fixture changes,
  `cargo test --locked -p webcodex --lib admin_project_paths -- --nocapture`:
  **0 passed, 2 failed**, exit 101. `D:\projects\demo` returned 400 instead of
  reaching empty Runner lookup (503); `/srv/projects/\0demo` reached Runner lookup
  instead of failing early with 400. These were executed assertions, not build failures.
- Final `cargo test --locked --offline -p webcodex --lib admin_`:
  **41 passed, 0 failed**, including both new path tests and admin authorization,
  same-origin and strict JSON coverage.
- Final `cargo test --locked --offline -p webcodex-core project_op_path`:
  **1 passed, 0 failed**; the unrelated integration benchmark had zero matching tests.
- `cargo fmt --all -- --check`: passed.
- `bash scripts/workspace_boundary_check.sh`: passed for all 22 workspace packages.
- `python3 -m unittest scripts.tests.test_workspace_boundary_check`: 20 passed.
- `python3 scripts/check_markdown_links.py` and `git diff --check`: passed.

The first offline build attempt could not download uncached `adler2 v2.0.1`.
Normal locked dependency retrieval succeeded; this initial environment failure
is not the fail-first evidence above. An initial Git fetch failed on unresolved
partial-clone deltas; ordinary refetch without common-commit negotiation succeeded.
Neither failure was an access denial. A direct invocation of the boundary Python
checker lacked its required arguments; its documented shell wrapper subsequently
passed. No test, deadline, permission or sandbox constraint was weakened.

## CI, review and acceptance limits

Upstream head `067011a186754feaad344abdc77f45591fbd1049` has 18 successful checks in
[upstream run 42643508654](https://github.com/yyjeqhc/webcodex/actions/runs/42643508654).
That is upstream evidence, not fork validation. Exact-head fork CI and final
independent review must be evaluated separately before merging this candidate.

The local tests are Linux in-process HTTP/validator tests. Valid path fixtures
intentionally stop at empty Runner lookup; they do not establish native Windows
filesystem acceptance. Full workspace/Server tests, native Windows/macOS/ARM64,
real Host/MCP, installed Server/Runner compatibility and Windows E2E were not run.
No release, deployment, service restart, upstream PR or force-push is included.
