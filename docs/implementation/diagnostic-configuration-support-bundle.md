# Diagnostic configuration in support bundles

WebCodex already has a user-facing diagnostic surface: Desktop **Settings → Diagnostics →
Export Support Bundle**. This document defines the additional
`diagnostic-configuration.json` entry included in that existing ZIP.

The projection is for bug reports, support, and configuration troubleshooting. It is
not a backup format, not an import format, and not a second configuration authority.
There is no standalone `settings-export` CLI command or separate Configuration & data
button.

## Contract

`diagnostic-configuration.json` is a bounded schema-version-1 document with:

- `kind: "diagnostic_configuration"`
- `cannot_restore: true`
- the current path-inventory revision as diagnostic correlation evidence
- the saved Environment ID
- local Server/Runner role state
- saved service scope
- up to 16 recorded Project IDs and path references
- the Runner's optional display name
- Desktop's effective current language and automatic-update-download preference

Each optional value is represented as `known`, `unknown`, or `not_applicable`.
Unknown state is preserved rather than replaced with an inferred default.

The projection reuses the authoritative, bounded Environment inventory reads. It does
not enumerate project directories, scan arbitrary configuration, invoke Runtime
processes, contact the network, or mutate Environment state.

## Privacy boundary

The document is an explicit typed allowlist. Credentials, API keys, tokens,
Server/Tunnel URLs, service arguments, arbitrary extension fields, raw mixed
configuration, databases, logs, recovery payloads, project contents, clipboard data,
and request/result payloads are excluded by construction.

Runner display names are bounded to 256 UTF-8 bytes and reject control characters,
URL/userinfo-like values, and values rejected by the existing sensitive-text guard.
Project paths and user-entered display names are still private metadata. The support
bundle UI therefore tells users that the diagnostic configuration can contain private
local paths and should be reviewed before sharing.

The existing copied diagnostic report remains more restrictive and does not gain these
configuration values. Only the explicit support-bundle export receives the additional
JSON entry.

## Revision and authority semantics

The existing `PathInventory.revision` continues to describe the serialized path
projection and Desktop selection context. Internal allowlisted diagnostic observations
are `serde(skip)` and do not change that revision.

Changing a Runner display name, Desktop language, or automatic-update preference must
not stale unrelated location navigation, path-inventory export, or backup-manifest
export. The current Desktop preferences are captured only when the user explicitly
exports a support bundle.

The diagnostic configuration never grants authority, copies identities or credentials,
registers Projects, changes service scope, or provides restore behavior. A future
backup/restore design remains a separate contract.

## Support-bundle integration

The support ZIP keeps its existing bounded diagnostic entries and additionally contains:

- `diagnostic-report.json`
- `diagnostic-report.md`
- `activity-safe.json`
- `diagnostic-configuration.json`

Each entry remains bounded by the existing support-bundle writer. The existing
create-new destination rule, no-overwrite behavior, and private Unix file mode remain
unchanged.

## Required regression coverage

Tests should keep proving that:

- real allowlisted values are projected without leaking raw configuration or secret
  canaries;
- malformed, duplicated, mismatched, secret-like, or unsafe Runner metadata becomes
  unknown;
- duplicate/truncated Project observations do not become authoritative values;
- the projection remains below the support attachment bound;
- changing hidden diagnostic values does not change the inventory/manifest revision;
- all supported Desktop locales map to the typed language enum;
- the support bundle contains `diagnostic-configuration.json` while preserving the
  existing exclusion guarantees;
- support export cannot overwrite an existing destination.

Platform-specific installed-application acceptance remains useful for native save
dialogs and filesystem ACL behavior, but this feature does not add a new native picker,
standalone CLI command, or independent export UI. The typed diagnostic JSON exists
only inside the existing support bundle contract.
