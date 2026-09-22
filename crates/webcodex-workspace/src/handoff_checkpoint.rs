//! Project-local, bounded handoff checkpoints.
//!
//! The checkpoint is deliberately separate from the Git workspace snapshot in
//! [`crate::workspace_checkpoint`].  It contains only typed, bounded facts
//! supplied by an already-authorized caller.  It never executes a command,
//! follows a project-local link, or treats a task file as an authority token.
//!
//! The public entry point has a small JSON boundary because both the local CLI
//! and the Server/Runner adapter use the same protocol:
//!
//! ```text
//! execute(project_root, {"action":"status"})
//! execute(project_root, {"action":"create", "task_id":"...", ...})
//! execute(project_root, {"action":"append", "expected_revision":1, ...})
//! ```
//!
//! On Unix the writer takes an inter-process lock, writes a same-directory
//! temporary file, syncs it, atomically renames it, and syncs the directory.
//! Other platforms return `unsupported_platform` rather than silently using a
//! weaker filesystem implementation.

use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::time::{Duration, Instant};

pub const INDEX_FILE_NAME: &str = "index.json";
pub const MAX_REQUEST_BYTES: usize = 128 * 1024;
pub const MAX_TASK_ID_CHARS: usize = 48;
pub const MAX_TITLE_CHARS: usize = 256;
pub const MAX_CLIENT_ID_CHARS: usize = 128;
pub const MAX_EVENT_ID_CHARS: usize = 128;
pub const MAX_EVENT_BYTES: usize = 16 * 1024;
pub const MAX_EVENT_COUNT: usize = 128;
pub const MAX_ARCHIVE_COUNT: usize = 64;
pub const MAX_TASK_COUNT: usize = 64;
pub const MAX_RETIRED_TASK_COUNT: usize = 128;
pub const MAX_RETIRED_BYTES: usize = 128 * 1024 * 1024;
pub const MAX_INDEX_BYTES: usize = 64 * 1024;
pub const MAX_TASK_BYTES: usize = 256 * 1024;
pub const MAX_MARKDOWN_BYTES: usize = 128 * 1024;
pub const MAX_TOTAL_BYTES: usize = 2 * 1024 * 1024;
pub const MAX_PATHS_PER_EVENT: usize = 32;
pub const MAX_PATH_CHARS: usize = 512;
pub const MAX_SUMMARY_CHARS: usize = 4096;

const HANDOFF_DIR_NAME: &str = "handoff";
const LOCK_FILE_NAME: &str = ".lock";
const INDEX_FORMAT: &str = "webcodex.handoff.index.v1";
const TASK_FORMAT: &str = "webcodex.handoff.task.v1";
const MANAGED_BY: &str = "webcodex";
const MACHINE_START: &str = "<!-- webcodex-handoff:machine:start -->";
const MACHINE_END: &str = "<!-- webcodex-handoff:machine:end -->";
const NOTES_START: &str = "<!-- webcodex-handoff:notes:start -->";
const NOTES_END: &str = "<!-- webcodex-handoff:notes:end -->";
const LOCK_WAIT: Duration = Duration::from_secs(5);
const LOCK_POLL: Duration = Duration::from_millis(10);

#[cfg(unix)]
mod volume_anchor;

/// Stable error object returned by [`execute`].  The `code` field is the
/// contract; `message` is intentionally generic and never contains OS text.
pub fn error(code: &'static str, message: &'static str) -> Value {
    json!({
        "code": code,
        "message": message,
        "state_changed": false,
    })
}

#[cfg(unix)]
fn mark_state_changed(mut value: Value) -> Value {
    value["state_changed"] = Value::Bool(true);
    value
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct ProjectIdentity {
    canonical_root: String,
    device: u64,
    inode: u64,
    root_fingerprint: String,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct TaskSummary {
    task_id: String,
    title: String,
    status: String,
    revision: u64,
    updated_at: i64,
    event_count: usize,
    unknown_count: usize,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct IndexFile {
    format: String,
    version: u32,
    managed_by: String,
    enabled: bool,
    project_identity: ProjectIdentity,
    revision: u64,
    updated_at: i64,
    #[serde(default)]
    tasks: Vec<TaskSummary>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    retired_tasks: Vec<TaskSummary>,
    #[serde(default)]
    bindings: BTreeMap<String, String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct EventArchive {
    file: String,
    sha256: String,
    event_count: usize,
    bytes: usize,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct TaskFile {
    format: String,
    version: u32,
    managed_by: String,
    project_identity: ProjectIdentity,
    task_id: String,
    title: String,
    status: String,
    revision: u64,
    created_at: i64,
    updated_at: i64,
    #[serde(default)]
    unknown_count: usize,
    #[serde(default)]
    events: Vec<Value>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    archives: Vec<EventArchive>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    event_aliases: BTreeMap<String, String>,
}

#[derive(Debug, Clone)]
struct NormalizedEvent {
    id: String,
    value: Value,
    unknown: bool,
}

#[derive(Debug, Clone)]
struct Binding {
    task_id: String,
    client_id: String,
}

#[derive(Debug, Clone)]
struct Request {
    action: String,
    task_id: Option<String>,
    title: Option<String>,
    expected_revision: Option<u64>,
    event: Option<NormalizedEvent>,
    client_id: Option<String>,
    binding: Option<Binding>,
}

#[cfg(unix)]
struct ProjectRoot {
    identity: ProjectIdentity,
    directory: fs::File,
}

#[cfg(unix)]
struct HandoffDir {
    directory: Option<fs::File>,
}

#[cfg(unix)]
impl HandoffDir {
    fn fd(&self) -> Option<std::os::unix::io::RawFd> {
        use std::os::unix::io::AsRawFd;
        self.directory.as_ref().map(AsRawFd::as_raw_fd)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum MarkdownState {
    Created,
    Updated,
    PreservedUnmanaged,
}

/// Execute one bounded handoff request for the exact project root.
///
/// `Err` is a JSON object instead of a Rust error so adapters can forward the
/// stable `code` field without exposing filesystem or parser implementation
/// details.
pub fn execute(root: &Path, request: Value) -> Result<Value, Value> {
    #[cfg(not(unix))]
    {
        let _ = (root, request);
        return Err(error(
            "unsupported_platform",
            "project handoff checkpoints are supported on Unix only",
        ));
    }

    #[cfg(unix)]
    {
        execute_unix(root, request, false)
    }
}

/// Runner-only archival entry: the Server must first freeze the exact task and
/// verify its delivery outbox. Local CLI requests cannot assert this authority.
pub fn execute_from_runner(root: &Path, request: Value) -> Result<Value, Value> {
    #[cfg(unix)]
    {
        execute_unix(root, request, true)
    }
    #[cfg(not(unix))]
    {
        execute(root, request)
    }
}

#[cfg(unix)]
fn execute_unix(root: &Path, request: Value, server_coordinated: bool) -> Result<Value, Value> {
    if request.get("action").and_then(Value::as_str) == Some("anchor_identity") {
        if server_coordinated {
            return Err(error(
                "invalid_action",
                "identity repair requires the local operator",
            ));
        }
        return volume_anchor::repair(root, request);
    }
    let parsed = parse_request(request)?;
    let project = open_project_root(root)?;
    let identity = &project.identity;

    match parsed.action.as_str() {
        "status" => with_read_lock(&project, |handoff| status(handoff, identity, &parsed)),
        "read" => with_read_lock(&project, |handoff| read(handoff, identity, &parsed)),
        "create" => with_write_lock(&project, |handoff| {
            let result = create(handoff, identity, &parsed)?;
            volume_anchor::create(&project, handoff).map_err(mark_state_changed)?;
            Ok(result)
        }),
        "append" => {
            with_existing_write_lock(&project, |handoff| append(handoff, identity, &parsed))
        }
        "bind" => with_existing_write_lock(&project, |handoff| bind(handoff, identity, &parsed)),
        "archive" => with_existing_write_lock(&project, |handoff| {
            archive_task(handoff, identity, &parsed, server_coordinated)
        }),
        "disable" => {
            with_existing_write_lock(&project, |handoff| disable(handoff, identity, &parsed))
        }
        _ => Err(error("invalid_action", "action is not supported")),
    }
}

fn parse_request(request: Value) -> Result<Request, Value> {
    let encoded = serde_json::to_vec(&request)
        .map_err(|_| error("invalid_request", "request is not valid JSON"))?;
    if encoded.len() > MAX_REQUEST_BYTES {
        return Err(error("request_too_large", "request exceeds its byte limit"));
    }
    let Some(object) = request.as_object() else {
        return Err(error("invalid_request", "request must be an object"));
    };
    for key in object.keys() {
        if !matches!(
            key.as_str(),
            "action"
                | "task_id"
                | "title"
                | "expected_revision"
                | "event"
                | "client_id"
                | "binding"
        ) {
            return Err(error(
                "invalid_request",
                "request contains an unknown field",
            ));
        }
    }
    let Some(action) = object.get("action").and_then(Value::as_str) else {
        return Err(error("invalid_request", "action is required"));
    };
    if !matches!(
        action,
        "status" | "read" | "create" | "append" | "bind" | "disable" | "archive"
    ) {
        return Err(error("invalid_action", "action is not supported"));
    }

    let task_id = object
        .get("task_id")
        .map(|value| parse_slug(value, "task_id", MAX_TASK_ID_CHARS))
        .transpose()?;
    let title = object
        .get("title")
        .map(|value| parse_text(value, "title", MAX_TITLE_CHARS, false))
        .transpose()?;
    let client_id = object
        .get("client_id")
        .map(|value| parse_actor_id(value, "client_id"))
        .transpose()?;
    let expected_revision = object
        .get("expected_revision")
        .map(|value| {
            value.as_u64().ok_or_else(|| {
                error(
                    "invalid_revision",
                    "expected_revision must be a non-negative integer",
                )
            })
        })
        .transpose()?;
    let event = object
        .get("event")
        .cloned()
        .map(normalize_event)
        .transpose()?;
    let binding = object.get("binding").map(parse_binding).transpose()?;

    if let (Some(task_id), Some(binding_task_id)) = (
        task_id.as_deref(),
        binding.as_ref().map(|b| b.task_id.as_str()),
    ) {
        if task_id != binding_task_id {
            return Err(error(
                "invalid_binding",
                "binding task_id does not match task_id",
            ));
        }
    }
    if let (Some(client_id), Some(binding_client_id)) = (
        client_id.as_deref(),
        binding.as_ref().map(|b| b.client_id.as_str()),
    ) {
        if client_id != binding_client_id {
            return Err(error(
                "invalid_binding",
                "binding client_id does not match client_id",
            ));
        }
    }

    let request = Request {
        action: action.to_string(),
        task_id,
        title,
        expected_revision,
        event,
        client_id,
        binding,
    };
    validate_action_request(&request)
}

fn validate_action_request(request: &Request) -> Result<Request, Value> {
    let has_binding = request.binding.is_some();
    match request.action.as_str() {
        "status" => {
            if request.task_id.is_some()
                || request.title.is_some()
                || request.expected_revision.is_some()
                || request.event.is_some()
                || has_binding
            {
                return Err(error("invalid_request", "status accepts only client_id"));
            }
        }
        "read" => {
            if request.task_id.is_none()
                || request.title.is_some()
                || request.expected_revision.is_some()
                || request.event.is_some()
                || request.client_id.is_some()
                || has_binding
            {
                return Err(error("invalid_request", "read requires only task_id"));
            }
        }
        "create" => {
            if request.task_id.is_none() || request.title.is_none() {
                return Err(error(
                    "invalid_request",
                    "create requires task_id and title",
                ));
            }
            if request.binding.as_ref().is_some_and(|binding| {
                binding.task_id != request.task_id.as_deref().unwrap_or_default()
            }) {
                return Err(error(
                    "invalid_binding",
                    "binding task_id does not match task_id",
                ));
            }
        }
        "append" => {
            if request.task_id.is_none()
                || request.expected_revision.is_none()
                || request.event.is_none()
                || request.title.is_some()
                || request.binding.is_some()
            {
                return Err(error(
                    "invalid_request",
                    "append requires task_id, expected_revision, and event",
                ));
            }
        }
        "bind" => {
            if request.task_id.is_none()
                || request.client_id.is_none() && request.binding.is_none()
                || request.title.is_some()
                || request.event.is_some()
            {
                return Err(error(
                    "invalid_request",
                    "bind requires task_id and client_id",
                ));
            }
        }
        "archive" => {
            if request.task_id.is_none()
                || request.expected_revision.is_none()
                || request.title.is_some()
                || request.event.is_some()
                || request.client_id.is_some()
                || has_binding
            {
                return Err(error(
                    "invalid_request",
                    "archive requires only task_id and expected_revision",
                ));
            }
        }
        "disable" => {
            if request.task_id.is_some()
                || request.title.is_some()
                || request.event.is_some()
                || request.client_id.is_some()
                || has_binding
            {
                return Err(error(
                    "invalid_request",
                    "disable accepts only expected_revision",
                ));
            }
        }
        _ => return Err(error("invalid_action", "action is not supported")),
    }
    Ok(request.clone())
}

fn parse_binding(value: &Value) -> Result<Binding, Value> {
    let Some(object) = value.as_object() else {
        return Err(error("invalid_binding", "binding must be an object"));
    };
    for key in object.keys() {
        if !matches!(key.as_str(), "task_id" | "client_id") {
            return Err(error(
                "invalid_binding",
                "binding contains an unknown field",
            ));
        }
    }
    let Some(task_id) = object
        .get("task_id")
        .map(|value| parse_slug(value, "task_id", MAX_TASK_ID_CHARS))
        .transpose()?
    else {
        return Err(error("invalid_binding", "binding task_id is required"));
    };
    let Some(client_id) = object
        .get("client_id")
        .map(|value| parse_actor_id(value, "client_id"))
        .transpose()?
    else {
        return Err(error("invalid_binding", "binding client_id is required"));
    };
    Ok(Binding { task_id, client_id })
}

fn parse_slug(value: &Value, field: &'static str, max: usize) -> Result<String, Value> {
    let Some(value) = value.as_str() else {
        return Err(error("invalid_task_id", "task_id must be a string"));
    };
    if value.is_empty() || value.chars().count() > max {
        return Err(error(
            "invalid_task_id",
            "task_id is outside its length limit",
        ));
    }
    if !value.bytes().enumerate().all(|(index, byte)| {
        if index == 0 {
            byte.is_ascii_lowercase() || byte.is_ascii_digit()
        } else {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-' || byte == b'_'
        }
    }) {
        let _ = field;
        return Err(error(
            "invalid_task_id",
            "task_id must be a short lowercase slug",
        ));
    }
    Ok(value.to_string())
}

fn parse_actor_id(value: &Value, field: &'static str) -> Result<String, Value> {
    let Some(value) = value.as_str() else {
        return Err(error("invalid_binding", "client_id must be a string"));
    };
    if value.is_empty() || value.chars().count() > MAX_CLIENT_ID_CHARS {
        return Err(error(
            "invalid_binding",
            "client_id is outside its length limit",
        ));
    }
    if !value.bytes().enumerate().all(|(index, byte)| {
        if index == 0 {
            byte.is_ascii_alphanumeric()
        } else {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b':' | b'_' | b'-')
        }
    }) {
        let _ = field;
        return Err(error(
            "invalid_binding",
            "client_id must be a bounded identifier",
        ));
    }
    Ok(value.to_string())
}

fn parse_text(
    value: &Value,
    _field: &'static str,
    max_chars: usize,
    allow_empty: bool,
) -> Result<String, Value> {
    let Some(value) = value.as_str() else {
        return Err(error("invalid_request", "text field must be a string"));
    };
    let value = value.trim();
    if (!allow_empty && value.is_empty()) || value.chars().count() > max_chars {
        return Err(error(
            "invalid_request",
            "text field is outside its length limit",
        ));
    }
    if value.chars().any(char::is_control) {
        return Err(error(
            "invalid_request",
            "text field contains control characters",
        ));
    }
    Ok(value.to_string())
}

fn normalize_event(value: Value) -> Result<NormalizedEvent, Value> {
    let Some(object) = value.as_object() else {
        return Err(error("invalid_event", "event must be an object"));
    };
    const ALLOWED: &[&str] = &[
        "event_id",
        "type",
        "source",
        "observed_at",
        "session_id",
        "job_id",
        "job_update_seq",
        "tool",
        "status",
        "outcome",
        "summary",
        "path",
        "paths",
        "exit_code",
        "duration_ms",
        "unknown",
        "success",
        "task_status",
        "error_code",
        "validation_name",
        "commit",
    ];
    for key in object.keys() {
        if !ALLOWED.contains(&key.as_str()) {
            return Err(error(
                "event_field_not_allowed",
                "event contains a field outside the typed fact schema",
            ));
        }
    }
    let Some(event_id) = object
        .get("event_id")
        .map(|value| parse_event_id(value))
        .transpose()?
    else {
        return Err(error("invalid_event", "event_id is required"));
    };
    let Some(event_type) = object
        .get("type")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
    else {
        return Err(error("invalid_event", "event type is required"));
    };
    if !event_type.bytes().all(|byte| {
        byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-')
    }) || !event_types().contains(&event_type)
    {
        return Err(error(
            "unsupported_event_type",
            "event type is not whitelisted",
        ));
    }

    let mut normalized = Map::new();
    normalized.insert("event_id".to_string(), json!(event_id));
    normalized.insert("type".to_string(), json!(event_type));
    for key in [
        "source",
        "observed_at",
        "session_id",
        "job_id",
        "job_update_seq",
        "tool",
        "status",
        "outcome",
        "summary",
        "path",
        "exit_code",
        "duration_ms",
        "unknown",
        "success",
        "task_status",
        "error_code",
        "validation_name",
        "commit",
    ] {
        if let Some(value) = object.get(key) {
            let normalized_value = normalize_event_field(key, value)?;
            normalized.insert(key.to_string(), normalized_value);
        }
    }
    if let Some(paths) = object.get("paths") {
        let Some(paths) = paths.as_array() else {
            return Err(error("invalid_event", "paths must be an array of strings"));
        };
        if paths.len() > MAX_PATHS_PER_EVENT {
            return Err(error("event_too_large", "event has too many paths"));
        }
        let mut normalized_paths = Vec::with_capacity(paths.len());
        for path in paths {
            normalized_paths.push(normalize_event_path(path)?);
        }
        normalized.insert("paths".to_string(), json!(normalized_paths));
    }
    let value = Value::Object(normalized);
    let bytes = serde_json::to_vec(&value)
        .map_err(|_| error("invalid_event", "event is not serializable"))?;
    if bytes.len() > MAX_EVENT_BYTES {
        return Err(error("event_too_large", "event exceeds its byte limit"));
    }
    let unknown = value
        .get("unknown")
        .and_then(Value::as_bool)
        .unwrap_or(false)
        || value
            .get("status")
            .and_then(Value::as_str)
            .is_some_and(is_unknown_status)
        || value
            .get("outcome")
            .and_then(Value::as_str)
            .is_some_and(is_unknown_status);
    Ok(NormalizedEvent {
        id: event_id,
        value,
        unknown,
    })
}

fn event_types() -> &'static [&'static str] {
    &[
        "task_created",
        "task_selected",
        "task_bound",
        "task_completed",
        "task_blocked",
        "session_started",
        "session_continued",
        "session_finished",
        "tool_started",
        "tool_finished",
        "file_changed",
        "file_edit",
        "file_read",
        "job_accepted",
        "job_queued",
        "job_started",
        "job_terminal",
        "validation_started",
        "validation_finished",
        "validation_result",
        "stage_started",
        "stage_finished",
        "handoff_started",
        "handoff_saved",
        "note_added",
    ]
}

fn parse_event_id(value: &Value) -> Result<String, Value> {
    let Some(value) = value.as_str() else {
        return Err(error("invalid_event_id", "event_id must be a string"));
    };
    if value.is_empty() || value.chars().count() > MAX_EVENT_ID_CHARS {
        return Err(error(
            "invalid_event_id",
            "event_id is outside its length limit",
        ));
    }
    if !value
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b':' | b'_' | b'-'))
    {
        return Err(error(
            "invalid_event_id",
            "event_id contains an invalid character",
        ));
    }
    Ok(value.to_string())
}

fn normalize_event_field(key: &str, value: &Value) -> Result<Value, Value> {
    match key {
        "source" => {
            let Some(source) = value.as_str() else {
                return Err(error("invalid_event", "source must be a string"));
            };
            if !matches!(
                source,
                "webcodex" | "local_codex" | "local" | "runner" | "gpt" | "user" | "system"
            ) {
                return Err(error(
                    "unsupported_event_source",
                    "event source is not whitelisted",
                ));
            }
            Ok(json!(source))
        }
        "job_update_seq" => value.as_u64().map(|n| json!(n)).ok_or_else(|| {
            error(
                "invalid_event",
                "job_update_seq must be a non-negative integer",
            )
        }),
        "observed_at" => value
            .as_i64()
            .map(Value::from)
            .ok_or_else(|| error("invalid_event", "observed_at must be an integer timestamp")),
        "session_id" | "job_id" | "tool" | "error_code" | "validation_name" | "commit" => {
            let Some(text) = value.as_str() else {
                return Err(error(
                    "invalid_event",
                    "event identifier fields must be strings",
                ));
            };
            if text.is_empty()
                || text.chars().count() > MAX_EVENT_ID_CHARS
                || text.chars().any(char::is_control)
            {
                return Err(error(
                    "invalid_event",
                    "event identifier field is outside its limit",
                ));
            }
            Ok(json!(text))
        }
        "status" | "outcome" | "task_status" => {
            let Some(value) = value.as_str() else {
                return Err(error("invalid_event", "status fields must be strings"));
            };
            if value.is_empty() || value.chars().count() > 64 || value.chars().any(char::is_control)
            {
                return Err(error("invalid_event", "status field is outside its limit"));
            }
            if key == "task_status"
                && !matches!(value, "active" | "completed" | "unknown" | "blocked")
            {
                return Err(error("invalid_event", "task_status is not supported"));
            }
            Ok(json!(value))
        }
        "summary" => Ok(json!(parse_text(
            value,
            "summary",
            MAX_SUMMARY_CHARS,
            false
        )?)),
        "path" => Ok(json!(normalize_event_path(value)?)),
        "exit_code" => {
            let Some(value) = value.as_i64() else {
                return Err(error("invalid_event", "exit_code must be an integer"));
            };
            Ok(json!(value))
        }
        "duration_ms" => {
            let Some(value) = value.as_u64() else {
                return Err(error("invalid_event", "duration_ms must be non-negative"));
            };
            if value > 31 * 24 * 60 * 60 * 1000 {
                return Err(error("invalid_event", "duration_ms exceeds its limit"));
            }
            Ok(json!(value))
        }
        "unknown" | "success" => value
            .as_bool()
            .map(Value::from)
            .ok_or_else(|| error("invalid_event", "boolean event fields must be booleans")),
        _ => Err(error(
            "event_field_not_allowed",
            "event field is not supported",
        )),
    }
}

fn normalize_event_path(value: &Value) -> Result<String, Value> {
    let Some(path) = value.as_str() else {
        return Err(error("invalid_event_path", "event paths must be strings"));
    };
    if path.is_empty()
        || path.chars().count() > MAX_PATH_CHARS
        || path.contains('\0')
        || path.starts_with('/')
        || path.starts_with('\\')
        || path.contains(':')
    {
        return Err(error(
            "invalid_event_path",
            "event path must be project-relative",
        ));
    }
    let normalized = path.replace('\\', "/");
    let components: Vec<_> = normalized
        .split('/')
        .filter(|component| !component.is_empty() && *component != ".")
        .collect();
    if components.is_empty()
        || components.iter().any(|component| *component == "..")
        || components
            .first()
            .is_some_and(|component| *component == HANDOFF_DIR_NAME)
        || crate::path_policy::sensitive_path(&normalized)
    {
        return Err(error(
            "invalid_event_path",
            "event path is outside the allowed fact scope",
        ));
    }
    Ok(components.join("/"))
}

fn is_unknown_status(value: &str) -> bool {
    matches!(
        value,
        "unknown" | "outcome_unknown" | "lost" | "delivery_unknown"
    )
}

#[cfg(unix)]
fn open_project_root(root: &Path) -> Result<ProjectRoot, Value> {
    if !root.is_absolute() {
        return Err(error("invalid_root", "project root must be absolute"));
    }
    let canonical = fs::canonicalize(root)
        .map_err(|_| error("project_root_unavailable", "project root is unavailable"))?;
    let metadata = fs::symlink_metadata(&canonical)
        .map_err(|_| error("project_root_unavailable", "project root is unavailable"))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(error("invalid_root", "project root must be a directory"));
    }
    use std::os::unix::fs::MetadataExt;
    let expected_device = metadata.dev();
    let expected_inode = metadata.ino();
    let directory = open_directory_path(&canonical)?;
    let (device, inode) = directory_identity(&directory)?;
    if device != expected_device || inode != expected_inode {
        return Err(error(
            "project_root_changed",
            "project root changed while it was being opened",
        ));
    }
    let canonical_root = canonical
        .to_str()
        .ok_or_else(|| error("invalid_root", "project root path is not valid UTF-8"))?
        .to_string();
    let mut hasher = Sha256::new();
    hasher.update(canonical_root.as_bytes());
    hasher.update(b"\0");
    hasher.update(device.to_le_bytes());
    hasher.update(inode.to_le_bytes());
    let root_fingerprint = format!("{:x}", hasher.finalize());
    let mut root = ProjectRoot {
        identity: ProjectIdentity {
            canonical_root,
            device,
            inode,
            root_fingerprint,
        },
        directory,
    };
    volume_anchor::resolve(&mut root)?;
    Ok(root)
}

#[cfg(unix)]
fn open_directory_path(path: &Path) -> Result<fs::File, Value> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::io::FromRawFd;

    let cpath = CString::new(path.as_os_str().as_bytes())
        .map_err(|_| error("invalid_root", "project root path contains a NUL byte"))?;
    let flags = libc::O_RDONLY | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_DIRECTORY;
    let fd = unsafe { libc::open(cpath.as_ptr(), flags) };
    if fd < 0 {
        let io_error = std::io::Error::last_os_error();
        return Err(if io_error.raw_os_error() == Some(libc::ELOOP) {
            error("unsafe_path", "project root is not a real directory")
        } else {
            error("project_root_unavailable", "project root cannot be opened")
        });
    }
    let directory = unsafe { fs::File::from_raw_fd(fd) };
    directory_identity(&directory)?;
    Ok(directory)
}

#[cfg(unix)]
fn directory_identity(directory: &fs::File) -> Result<(u64, u64), Value> {
    use std::os::unix::io::AsRawFd;

    let mut stat = std::mem::MaybeUninit::<libc::stat>::uninit();
    if unsafe { libc::fstat(directory.as_raw_fd(), stat.as_mut_ptr()) } != 0 {
        return Err(error(
            "project_root_unavailable",
            "project root cannot be inspected",
        ));
    }
    let stat = unsafe { stat.assume_init() };
    if stat.st_mode & libc::S_IFMT != libc::S_IFDIR {
        return Err(error("invalid_root", "project root must be a directory"));
    }
    Ok((stat.st_dev as u64, stat.st_ino as u64))
}

#[cfg(unix)]
fn with_read_lock<T>(
    root: &ProjectRoot,
    operation: impl FnOnce(&HandoffDir) -> Result<T, Value>,
) -> Result<T, Value> {
    let directory = match open_handoff_dir(root)? {
        Some(directory) => directory,
        None => return operation(&HandoffDir { directory: None }),
    };
    let lock = open_existing_at(&directory, LOCK_FILE_NAME)?;
    if let Some(lock) = &lock {
        acquire_lock_shared(lock)?;
    }
    let handle = directory;
    let result = operation(&handle);
    if let Some(lock) = lock {
        let _ = lock.unlock();
    }
    result
}

#[cfg(unix)]
fn with_write_lock<T>(
    root: &ProjectRoot,
    operation: impl FnOnce(&HandoffDir) -> Result<T, Value>,
) -> Result<T, Value> {
    let directory = ensure_handoff_dir(root)?;
    let lock = open_lock_for_write(&directory)?;
    acquire_lock_exclusive(&lock)?;
    let handle = directory;
    let result = operation(&handle);
    let _ = lock.unlock();
    result
}

#[cfg(unix)]
fn with_existing_write_lock<T>(
    root: &ProjectRoot,
    operation: impl FnOnce(&HandoffDir) -> Result<T, Value>,
) -> Result<T, Value> {
    let Some(directory) = open_handoff_dir(root)? else {
        return operation(&HandoffDir { directory: None });
    };
    let lock = open_lock_for_write(&directory)?;
    acquire_lock_exclusive(&lock)?;
    let result = operation(&directory);
    let _ = lock.unlock();
    result
}

#[cfg(unix)]
fn ensure_handoff_dir(root: &ProjectRoot) -> Result<HandoffDir, Value> {
    if let Some(directory) = open_handoff_dir(root)? {
        return Ok(directory);
    }
    use std::ffi::CString;
    use std::os::unix::io::AsRawFd;
    let name = CString::new(HANDOFF_DIR_NAME).expect("constant contains no NUL");
    let result = unsafe { libc::mkdirat(root.directory.as_raw_fd(), name.as_ptr(), 0o700) };
    if result == 0 {
        if root.directory.sync_all().is_err() {
            return Err(mark_state_changed(error(
                "io_error",
                "project root cannot be synced",
            )));
        }
    } else {
        let io_error = std::io::Error::last_os_error();
        if io_error.kind() != std::io::ErrorKind::AlreadyExists {
            return Err(if io_error.raw_os_error() == Some(libc::ELOOP) {
                error("unsafe_path", "handoff path is not a real directory")
            } else {
                error("io_error", "handoff directory cannot be created")
            });
        }
    }
    open_handoff_dir(root)?.ok_or_else(|| error("io_error", "handoff directory cannot be opened"))
}

#[cfg(unix)]
fn open_handoff_dir(root: &ProjectRoot) -> Result<Option<HandoffDir>, Value> {
    use std::ffi::CString;
    use std::os::unix::io::AsRawFd;
    use std::os::unix::io::FromRawFd;

    let name = CString::new(HANDOFF_DIR_NAME).expect("constant contains no NUL");
    let flags = libc::O_RDONLY | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_DIRECTORY;
    let fd = unsafe { libc::openat(root.directory.as_raw_fd(), name.as_ptr(), flags) };
    if fd < 0 {
        let io_error = std::io::Error::last_os_error();
        if io_error.kind() == std::io::ErrorKind::NotFound {
            return Ok(None);
        }
        if io_error.raw_os_error() == Some(libc::ELOOP) {
            return Err(error("unsafe_path", "handoff path is not a real directory"));
        }
        return Err(error("io_error", "handoff directory cannot be opened"));
    }
    let directory = unsafe { fs::File::from_raw_fd(fd) };
    directory_identity(&directory)?;
    Ok(Some(HandoffDir {
        directory: Some(directory),
    }))
}

#[cfg(unix)]
fn open_at(
    directory: &HandoffDir,
    name: &str,
    create_new: bool,
) -> Result<Option<fs::File>, Value> {
    use std::ffi::CString;
    use std::os::unix::io::FromRawFd;
    let Some(dir_fd) = directory.fd() else {
        return Err(error("io_error", "handoff directory is not open"));
    };
    let cname =
        CString::new(name).map_err(|_| error("invalid_request", "handoff file name is invalid"))?;
    let mut flags = libc::O_CLOEXEC | libc::O_NOFOLLOW;
    if create_new {
        flags |= libc::O_RDWR | libc::O_CREAT | libc::O_EXCL;
    } else {
        flags |= libc::O_RDONLY;
    }
    let fd = unsafe { libc::openat(dir_fd, cname.as_ptr(), flags, 0o600) };
    if fd < 0 {
        let io_error = std::io::Error::last_os_error();
        if !create_new && io_error.kind() == std::io::ErrorKind::NotFound {
            return Ok(None);
        }
        if io_error.raw_os_error() == Some(libc::ELOOP) {
            return Err(error("unsafe_path", "handoff file cannot be a symlink"));
        }
        if create_new && io_error.kind() == std::io::ErrorKind::AlreadyExists {
            return Err(error("target_exists", "handoff file already exists"));
        }
        return Err(if create_new {
            error("io_error", "handoff file cannot be created")
        } else {
            error("io_error", "handoff file cannot be opened")
        });
    }
    let file = unsafe { fs::File::from_raw_fd(fd) };
    let mut stat = std::mem::MaybeUninit::<libc::stat>::uninit();
    if unsafe { libc::fstat(fd, stat.as_mut_ptr()) } != 0 {
        return Err(error("io_error", "handoff file cannot be inspected"));
    }
    let stat = unsafe { stat.assume_init() };
    if stat.st_mode & libc::S_IFMT != libc::S_IFREG || stat.st_nlink != 1 {
        return Err(error(
            "unsafe_path",
            "handoff file must be a single-link regular file",
        ));
    }
    Ok(Some(file))
}

#[cfg(unix)]
fn open_existing_at(directory: &HandoffDir, name: &str) -> Result<Option<fs::File>, Value> {
    open_at(directory, name, false)
}

#[cfg(unix)]
fn acquire_lock_shared(file: &fs::File) -> Result<(), Value> {
    let deadline = Instant::now() + LOCK_WAIT;
    loop {
        match fs2::FileExt::try_lock_shared(file) {
            Ok(()) => return Ok(()),
            Err(io_error) if io_error.kind() == std::io::ErrorKind::WouldBlock => {
                if Instant::now() >= deadline {
                    return Err(error("lock_timeout", "handoff lock acquisition timed out"));
                }
                std::thread::sleep(LOCK_POLL);
            }
            Err(_) => return Err(error("lock_unavailable", "handoff lock cannot be acquired")),
        }
    }
}

#[cfg(unix)]
fn acquire_lock_exclusive(file: &fs::File) -> Result<(), Value> {
    let deadline = Instant::now() + LOCK_WAIT;
    loop {
        match fs2::FileExt::try_lock_exclusive(file) {
            Ok(()) => return Ok(()),
            Err(io_error) if io_error.kind() == std::io::ErrorKind::WouldBlock => {
                if Instant::now() >= deadline {
                    return Err(error("lock_timeout", "handoff lock acquisition timed out"));
                }
                std::thread::sleep(LOCK_POLL);
            }
            Err(_) => return Err(error("lock_unavailable", "handoff lock cannot be acquired")),
        }
    }
}

#[cfg(unix)]
fn open_lock_for_write(directory: &HandoffDir) -> Result<fs::File, Value> {
    if let Some(lock) = open_existing_at(directory, LOCK_FILE_NAME)? {
        return Ok(lock);
    }
    let lock = match open_at(directory, LOCK_FILE_NAME, true) {
        Ok(Some(lock)) => lock,
        Err(err) if err["code"] == "target_exists" => open_existing_at(directory, LOCK_FILE_NAME)?
            .ok_or_else(|| error("lock_unavailable", "handoff lock cannot be opened"))?,
        Err(err) => return Err(err),
        Ok(None) => return Err(error("lock_unavailable", "handoff lock cannot be created")),
    };
    if lock.sync_all().is_err() {
        return Err(mark_state_changed(error(
            "io_error",
            "handoff lock cannot be synced",
        )));
    }
    if let Err(err) = sync_directory_handle(directory) {
        return Err(mark_state_changed(err));
    }
    Ok(lock)
}

#[cfg(unix)]
fn sync_directory_handle(directory: &HandoffDir) -> Result<(), Value> {
    directory
        .directory
        .as_ref()
        .ok_or_else(|| error("io_error", "handoff directory is not open"))?
        .sync_all()
        .map_err(|_| error("io_error", "handoff directory cannot be synced"))
}

#[cfg(unix)]
fn read_file_bounded(
    handoff: &HandoffDir,
    name: &str,
    limit: usize,
    code: &'static str,
) -> Result<Option<Vec<u8>>, Value> {
    if handoff.fd().is_none() {
        return Ok(None);
    }
    let Some(file) = open_existing_at(handoff, name)? else {
        return Ok(None);
    };
    let metadata = file
        .metadata()
        .map_err(|_| error("io_error", "handoff file cannot be inspected"))?;
    if metadata.len() > limit as u64 {
        return Err(error(code, "handoff file exceeds its capacity limit"));
    }
    let mut bytes = Vec::new();
    use std::io::Read;
    file.take((limit as u64).saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|_| error("io_error", "handoff file cannot be read"))?;
    if bytes.len() > limit {
        return Err(error(code, "handoff file exceeds its capacity limit"));
    }
    Ok(Some(bytes))
}

#[cfg(unix)]
fn load_index(
    handoff: &HandoffDir,
    identity: &ProjectIdentity,
) -> Result<Option<IndexFile>, Value> {
    let Some(bytes) = read_file_bounded(
        handoff,
        INDEX_FILE_NAME,
        MAX_INDEX_BYTES,
        "capacity_exceeded",
    )?
    else {
        return Ok(None);
    };
    let index: IndexFile = serde_json::from_slice(&bytes).map_err(|_| {
        error(
            "malformed_index",
            "handoff index is not a supported managed file",
        )
    })?;
    validate_index(&index, identity)?;
    Ok(Some(index))
}

#[cfg(unix)]
fn validate_index(index: &IndexFile, identity: &ProjectIdentity) -> Result<(), Value> {
    if index.format != INDEX_FORMAT
        || !matches!(index.version, 1 | 2)
        || index.managed_by != MANAGED_BY
    {
        return Err(error(
            "non_managed_file",
            "handoff index is not managed by WebCodex",
        ));
    }
    if &index.project_identity != identity {
        return Err(error(
            "project_identity_mismatch",
            "handoff belongs to another directory",
        ));
    }
    if index.revision == 0
        || index.tasks.len() > MAX_TASK_COUNT
        || index.retired_tasks.len() > MAX_RETIRED_TASK_COUNT
        || (index.version == 1 && !index.retired_tasks.is_empty())
    {
        return Err(error(
            "malformed_index",
            "handoff index is outside its limits",
        ));
    }
    let mut ids = std::collections::HashSet::new();
    for task in index.tasks.iter().chain(&index.retired_tasks) {
        parse_slug(
            &Value::String(task.task_id.clone()),
            "task_id",
            MAX_TASK_ID_CHARS,
        )?;
        parse_text(
            &Value::String(task.title.clone()),
            "title",
            MAX_TITLE_CHARS,
            false,
        )?;
        if !matches!(
            task.status.as_str(),
            "active" | "completed" | "unknown" | "blocked"
        ) || task.revision == 0
            || !ids.insert(task.task_id.as_str())
        {
            return Err(error("malformed_index", "handoff task summary is invalid"));
        }
    }
    for (client_id, task_id) in &index.bindings {
        parse_actor_id(&Value::String(client_id.clone()), "client_id")?;
        parse_slug(
            &Value::String(task_id.clone()),
            "task_id",
            MAX_TASK_ID_CHARS,
        )?;
        if !ids.contains(task_id.as_str()) {
            return Err(error(
                "malformed_index",
                "handoff binding references no task",
            ));
        }
    }
    Ok(())
}

#[cfg(unix)]
fn load_task(
    handoff: &HandoffDir,
    identity: &ProjectIdentity,
    task_id: &str,
) -> Result<TaskFile, Value> {
    let name = task_file_name(task_id);
    let Some(bytes) = read_file_bounded(handoff, &name, MAX_TASK_BYTES, "capacity_exceeded")?
    else {
        return Err(error("task_missing", "managed task file is missing"));
    };
    let mut task: TaskFile = serde_json::from_slice(&bytes)
        .map_err(|_| error("malformed_task", "managed task file is invalid"))?;
    // Archived segments are immutable and verified before deduplication or
    // projections use them. Never infer an empty history from a missing file.
    if task.archives.len() > MAX_ARCHIVE_COUNT || task.events.len() > MAX_EVENT_COUNT {
        return Err(error("malformed_task", "task segment limits exceeded"));
    }
    let mut history = Vec::new();
    let mut total = 0usize;
    for archive in &task.archives {
        validate_archive_reference(archive, task_id)?;
        total = total.saturating_add(archive.bytes);
        if total > MAX_TOTAL_BYTES {
            return Err(error(
                "capacity_exceeded",
                "archived history exceeds budget",
            ));
        }
        let bytes = read_file_bounded(handoff, &archive.file, MAX_TASK_BYTES, "capacity_exceeded")?
            .ok_or_else(|| error("archive_missing", "archived history is missing"))?;
        if bytes.len() != archive.bytes || format!("{:x}", Sha256::digest(&bytes)) != archive.sha256
        {
            return Err(error(
                "archive_corrupt",
                "archived history checksum differs",
            ));
        }
        let events: Vec<Value> = serde_json::from_slice(&bytes)
            .map_err(|_| error("archive_corrupt", "archived events are invalid"))?;
        if events.len() != archive.event_count {
            return Err(error("archive_corrupt", "archived event count differs"));
        }
        history.extend(events);
    }
    history.append(&mut task.events);
    task.events = history;
    validate_task(&task, identity)?;
    if task.task_id != task_id {
        return Err(error(
            "malformed_task",
            "managed task file has the wrong task id",
        ));
    }
    Ok(task)
}

#[cfg(unix)]
fn validate_task(task: &TaskFile, identity: &ProjectIdentity) -> Result<(), Value> {
    if task.format != TASK_FORMAT || task.version != 1 || task.managed_by != MANAGED_BY {
        return Err(error(
            "non_managed_file",
            "task file is not managed by WebCodex",
        ));
    }
    if &task.project_identity != identity
        || task.revision == 0
        || task.events.len() > MAX_EVENT_COUNT * (MAX_ARCHIVE_COUNT + 1)
        || !matches!(
            task.status.as_str(),
            "active" | "completed" | "unknown" | "blocked"
        )
    {
        return Err(error("malformed_task", "task file is outside its limits"));
    }
    parse_slug(
        &Value::String(task.task_id.clone()),
        "task_id",
        MAX_TASK_ID_CHARS,
    )?;
    parse_text(
        &Value::String(task.title.clone()),
        "title",
        MAX_TITLE_CHARS,
        false,
    )?;
    let mut event_ids = std::collections::HashSet::new();
    for event in &task.events {
        let normalized = normalize_event(event.clone())?;
        if !event_ids.insert(normalized.id) {
            return Err(error("malformed_task", "task contains duplicate event ids"));
        }
    }
    for (id, fingerprint) in &task.event_aliases {
        parse_event_id(&Value::String(id.clone()))?;
        if event_ids.contains(id)
            || fingerprint.len() != 64
            || !fingerprint
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        {
            return Err(error("malformed_task", "invalid event alias"));
        }
    }
    let unknown_count = task
        .events
        .iter()
        .filter_map(|event| normalize_event(event.clone()).ok())
        .filter(|event| event.unknown)
        .count();
    if unknown_count != task.unknown_count {
        return Err(error(
            "malformed_task",
            "task unknown fact count is invalid",
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn task_file_name(task_id: &str) -> String {
    format!("{task_id}.json")
}

#[cfg(unix)]
fn markdown_file_name(task_id: &str) -> String {
    format!("{task_id}.md")
}

#[cfg(unix)]
fn disabled_response() -> Value {
    json!({
        "enabled": false,
        "status": "disabled",
        "tasks": [],
    })
}

#[cfg(unix)]
fn status(
    handoff: &HandoffDir,
    identity: &ProjectIdentity,
    request: &Request,
) -> Result<Value, Value> {
    let Some(index) = load_index(handoff, identity)? else {
        return Ok(disabled_response());
    };
    if !index.enabled {
        return Ok(disabled_response());
    }
    let mut tasks = Vec::with_capacity(index.tasks.len());
    let mut index_stale = false;
    for summary in &index.tasks {
        let task = load_task(handoff, identity, &summary.task_id)?;
        if task_summary_struct(&task) != *summary {
            index_stale = true;
        }
        tasks.push(task_summary(&task));
    }
    tasks.sort_by(|left, right| left["task_id"].as_str().cmp(&right["task_id"].as_str()));
    let used_bytes = total_capacity_bytes(handoff, &index, "", &[], None)?;
    let mut output = json!({
        "enabled": true,
        "status": "enabled",
        "revision": index.revision,
        "tasks": tasks,
        "archived_tasks": index.retired_tasks,
        "archive_capacity": {"tasks": MAX_RETIRED_TASK_COUNT, "bytes": MAX_RETIRED_BYTES},
        "capacity": capacity_output(),
        "usage": {
            "tasks": index.tasks.len(), "bytes": used_bytes,
            "near_limit": index.tasks.len() * 5 >= MAX_TASK_COUNT * 4
                || used_bytes.saturating_mul(5) >= MAX_TOTAL_BYTES * 4,
        },
    });
    if let Some(client_id) = &request.client_id {
        output["bound_task_id"] = index
            .bindings
            .get(client_id)
            .filter(|id| index.tasks.iter().any(|task| &task.task_id == *id))
            .map(|task_id| json!(task_id))
            .unwrap_or(Value::Null);
    }
    if index_stale {
        output["integrity"] = json!("index_stale");
    }
    Ok(output)
}

#[cfg(unix)]
fn read(
    handoff: &HandoffDir,
    identity: &ProjectIdentity,
    request: &Request,
) -> Result<Value, Value> {
    let Some(index) = load_index(handoff, identity)? else {
        return Ok(json!({
            "enabled": false,
            "status": "disabled",
            "checkpoint": Value::Null,
        }));
    };
    if !index.enabled {
        return Ok(json!({
            "enabled": false,
            "status": "disabled",
            "checkpoint": Value::Null,
        }));
    }
    let task_id = request.task_id.as_deref().expect("validated read task_id");
    let archived = index
        .retired_tasks
        .iter()
        .any(|summary| summary.task_id == task_id);
    if !archived && !index.tasks.iter().any(|summary| summary.task_id == task_id) {
        return Err(error("task_not_found", "task does not exist"));
    }
    let task = load_task(handoff, identity, task_id)?;
    let jobs = job_projection(&task);
    let mut output = json!({
        "enabled": true,
        "status": "ready",
        "archived": archived,
        "task_id": task.task_id,
        "revision": task.revision,
        "jobs": jobs.iter().take(MAX_EVENT_COUNT).collect::<Vec<_>>(),
        "jobs_total": jobs.len(),
        "jobs_truncated": jobs.len() > MAX_EVENT_COUNT,
        "history": {"archived_events": archived_count(&task), "files": task.archives.iter().map(|a| format!("handoff/{}", a.file)).collect::<Vec<_>>()},
        "event_count": task.events.len(),
        "checkpoint": serde_json::to_value(task_disk_view(&task))
            .map_err(|_| error("malformed_task", "task cannot be serialized"))?,
    });
    if index
        .tasks
        .iter()
        .find(|summary| summary.task_id == task_id)
        .is_some_and(|summary| task_summary_struct(&task) != *summary)
    {
        output["integrity"] = json!("index_stale");
    }
    Ok(output)
}

#[cfg(unix)]
fn create(
    handoff: &HandoffDir,
    identity: &ProjectIdentity,
    request: &Request,
) -> Result<Value, Value> {
    let task_id = request
        .task_id
        .as_deref()
        .expect("validated create task_id");
    let title = request.title.as_deref().expect("validated create title");
    let (mut index, replace_index) = match load_index(handoff, identity)? {
        Some(index) => (index, true),
        None => (
            IndexFile {
                format: INDEX_FORMAT.to_string(),
                version: 1,
                managed_by: MANAGED_BY.to_string(),
                enabled: true,
                project_identity: identity.clone(),
                revision: 0,
                updated_at: now_unix(),
                tasks: Vec::new(),
                retired_tasks: Vec::new(),
                bindings: BTreeMap::new(),
            },
            false,
        ),
    };
    if index
        .tasks
        .iter()
        .chain(&index.retired_tasks)
        .any(|summary| summary.task_id == task_id)
    {
        return Err(error("task_exists", "task already exists"));
    }
    if index.tasks.len() >= MAX_TASK_COUNT {
        return Err(error("capacity_exceeded", "task count capacity is full"));
    }
    if let Some(expected) = request.expected_revision {
        let actual = index.revision;
        if actual != 0 && expected != actual {
            return Err(revision_conflict(expected, actual));
        }
        if actual == 0 && expected != 0 {
            return Err(revision_conflict(expected, actual));
        }
    }

    let task_name = task_file_name(task_id);
    if let Some(metadata) = target_metadata(handoff, &task_name)? {
        if metadata.size > MAX_TASK_BYTES as u64 {
            return Err(error(
                "capacity_exceeded",
                "task file exceeds its capacity limit",
            ));
        }
        return Err(error(
            "non_managed_file",
            "task path already contains a file",
        ));
    }
    let task = new_task(identity, task_id, title, request.event.as_ref());
    let markdown_name = markdown_file_name(task_id);
    let markdown = markdown_plan(handoff, &markdown_name, &task)?;
    let summary = task_summary_struct(&task);
    index.tasks.push(summary);
    index
        .tasks
        .sort_by(|left, right| left.task_id.cmp(&right.task_id));
    index.enabled = true;
    index.revision = next_revision(index.revision)?;
    index.updated_at = now_unix();
    apply_binding(&mut index, request, task_id)?;
    let index_bytes = serialize_index(&index)?;
    let task_bytes = serialize_task(&task)?;
    check_total_capacity(
        handoff,
        &index,
        task_id,
        &task_bytes,
        markdown.bytes.as_deref(),
    )?;

    let mut markdown_written = false;
    if let Err(err) = atomic_write(handoff, &task_name, &task_bytes, false) {
        return Err(err);
    }
    if let Some(bytes) = markdown.bytes.as_deref() {
        if let Err(err) = atomic_write(handoff, &markdown_name, bytes, false) {
            let cleanup_failed = remove_file_at(handoff, &task_name);
            return Err(if cleanup_failed {
                mark_state_changed(err)
            } else {
                err
            });
        }
        markdown_written = true;
    }
    if let Err(err) = atomic_write(handoff, INDEX_FILE_NAME, &index_bytes, replace_index) {
        // If the index rename reached the directory, keep the task and
        // Markdown so the next read/append can repair a partially committed
        // multi-file update.  Removing them would make a durable index point
        // at missing state.
        if !err["state_changed"].as_bool().unwrap_or(false) {
            let mut cleanup_failed = remove_file_at(handoff, &task_name);
            if markdown_written {
                cleanup_failed |= remove_file_at(handoff, &markdown_name);
            }
            return Err(if cleanup_failed {
                mark_state_changed(err)
            } else {
                err
            });
        }
        return Err(err);
    }
    Ok(json!({
        "status": "saved",
        "task_id": task_id,
        "revision": task.revision,
        "index_revision": index.revision,
        "markdown": markdown.state.as_str(),
    }))
}

#[cfg(unix)]
fn append(
    handoff: &HandoffDir,
    identity: &ProjectIdentity,
    request: &Request,
) -> Result<Value, Value> {
    let task_id = request
        .task_id
        .as_deref()
        .expect("validated append task_id");
    let expected = request
        .expected_revision
        .expect("validated append revision");
    let event = request.event.as_ref().expect("validated append event");
    let mut index = load_index(handoff, identity)?
        .ok_or_else(|| error("handoff_disabled", "handoff is not enabled"))?;
    if !index.enabled {
        return Err(error("handoff_disabled", "handoff is not enabled"));
    }
    let summary_position = index
        .tasks
        .iter()
        .position(|summary| summary.task_id == task_id)
        .ok_or_else(|| error("task_not_found", "task does not exist"))?;
    let mut task = load_task(handoff, identity, task_id)?;
    if let Some(existing) = task.events.iter().find(|existing| {
        existing.get("event_id").and_then(Value::as_str) == Some(event.id.as_str())
    }) {
        if existing != &event.value {
            return Err(error(
                "event_id_conflict",
                "event_id already has different facts",
            ));
        }
    }
    let fingerprint = format!(
        "{:x}",
        Sha256::digest(
            serde_json::to_vec(&event.value)
                .map_err(|_| error("invalid_event", "event cannot be fingerprinted"))?
        )
    );
    let known_alias = task.event_aliases.get(&event.id);
    if known_alias.is_some_and(|saved| saved != &fingerprint) {
        return Err(error(
            "event_id_conflict",
            "event_id already has different facts",
        ));
    }
    let alias_seen = known_alias.is_some();
    // The Runner writes terminal Job facts directly so they survive a Server
    // outage. Later, the Server receipt path may deliver the same immutable
    // update with its own event id. Deduplicate that replicated fact here,
    // where both paths share one atomic checkpoint writer. The source and
    // observation time intentionally differ; a conflicting result stays
    // visible rather than being silently collapsed.
    if alias_seen
        || task.events.iter().any(|existing| {
            existing.get("event_id").and_then(Value::as_str) == Some(event.id.as_str())
                || same_terminal_job_fact(existing, &event.value)
        })
    {
        let markdown_name = markdown_file_name(task_id);
        let markdown = markdown_plan(handoff, &markdown_name, &task)?;
        // Remember every acknowledged transport ID. Metadata-only persistence
        // does not add a fact or advance its revision; file/total byte limits
        // still apply, and a failure must not acknowledge the alias.
        if !alias_seen && !task.events.iter().any(|e| e["event_id"] == event.id) {
            task.event_aliases.insert(event.id.clone(), fingerprint);
            let bytes = serialize_task(&task)?;
            check_total_capacity(handoff, &index, task_id, &bytes, markdown.bytes.as_deref())?;
            atomic_write(handoff, &task_file_name(task_id), &bytes, true)?;
        }
        // A previous attempt may have committed JSON but failed before
        // writing its Markdown projection. Idempotency repairs both views.
        if let Some(bytes) = markdown.bytes.as_deref() {
            atomic_write_checked(
                handoff,
                &markdown_name,
                bytes,
                true,
                Some(markdown.original.as_deref()),
            )
            .map_err(mark_state_changed)?;
        }
        let index_repaired = repair_index_projection(handoff, &mut index, &task, summary_position)
            .map_err(mark_state_changed)?;
        return Ok(json!({
            "status": "duplicate",
            "task_id": task_id,
            "revision": task.revision,
            "event_id": event.id,
            "index_revision": index.revision,
            "index_repaired": index_repaired,
        }));
    }
    if task.revision != expected {
        return Err(revision_conflict(expected, task.revision));
    }
    task.events.push(event.value.clone());
    task.unknown_count = task
        .unknown_count
        .saturating_add(usize::from(event.unknown));
    task.status = next_task_status(&task.status, event);
    task.revision = next_revision(task.revision)?;
    task.updated_at = now_unix();
    let new_summary = task_summary_struct(&task);
    let summary_position = index
        .tasks
        .iter()
        .position(|summary| summary.task_id == task_id)
        .expect("summary was found");
    index.tasks[summary_position] = new_summary;
    index.revision = next_revision(index.revision)?;
    index.updated_at = now_unix();

    let archive = plan_archive(&mut task)?;
    let task_bytes = serialize_task(&task)?;
    let task_name = task_file_name(task_id);
    let markdown_name = markdown_file_name(task_id);
    let markdown = markdown_plan(handoff, &markdown_name, &task)?;
    let index_bytes = serialize_index(&index)?;
    check_total_capacity(
        handoff,
        &index,
        task_id,
        &task_bytes,
        markdown.bytes.as_deref(),
    )?;
    if let Some((name, bytes)) = archive {
        match read_file_bounded(handoff, &name, MAX_TASK_BYTES, "capacity_exceeded")? {
            Some(existing) if existing == bytes => {} // retry after archive commit
            Some(_) => {
                return Err(error(
                    "archive_conflict",
                    "archive path has different content",
                ))
            }
            None => atomic_write(handoff, &name, &bytes, false)?,
        }
    }
    atomic_write(handoff, &task_name, &task_bytes, true)?;
    if let Some(bytes) = markdown.bytes.as_deref() {
        atomic_write_checked(
            handoff,
            &markdown_name,
            bytes,
            true,
            Some(markdown.original.as_deref()),
        )
        .map_err(mark_state_changed)?;
    }
    atomic_write(handoff, INDEX_FILE_NAME, &index_bytes, true).map_err(mark_state_changed)?;
    Ok(json!({
        "status": "saved",
        "task_id": task_id,
        "revision": task.revision,
        "index_revision": index.revision,
        "event_id": event.id,
        "markdown": markdown.state.as_str(),
    }))
}

#[cfg(unix)]
fn same_terminal_job_fact(existing: &Value, incoming: &Value) -> bool {
    // Only transport metadata may differ. Agent notes and any added fields
    // are distinct evidence, even if they refer to the same Job update.
    matches!(
        (existing["source"].as_str(), incoming["source"].as_str()),
        (Some("runner"), Some("webcodex")) | (Some("webcodex"), Some("runner"))
    ) && existing["type"] == "job_terminal"
        && incoming["type"] == "job_terminal"
        && existing["job_id"].as_str().is_some_and(|s| !s.is_empty())
        && existing["job_update_seq"].as_u64().is_some()
        && existing["status"].as_str().is_some()
        && existing
            .as_object()
            .unwrap()
            .iter()
            .filter(|(k, _)| !matches!(k.as_str(), "event_id" | "source" | "observed_at"))
            .eq(incoming
                .as_object()
                .unwrap()
                .iter()
                .filter(|(k, _)| !matches!(k.as_str(), "event_id" | "source" | "observed_at")))
}

#[cfg(unix)]
fn repair_index_projection(
    handoff: &HandoffDir,
    index: &mut IndexFile,
    task: &TaskFile,
    summary_position: usize,
) -> Result<bool, Value> {
    let summary = task_summary_struct(task);
    if index.tasks[summary_position] == summary {
        return Ok(false);
    }
    index.tasks[summary_position] = summary;
    index.revision = next_revision(index.revision)?;
    index.updated_at = now_unix();
    let index_bytes = serialize_index(index)?;
    let task_bytes = serialize_task(task)?;
    check_total_capacity(handoff, index, &task.task_id, &task_bytes, None)?;
    atomic_write(handoff, INDEX_FILE_NAME, &index_bytes, true)?;
    Ok(true)
}

#[cfg(unix)]
fn bind(
    handoff: &HandoffDir,
    identity: &ProjectIdentity,
    request: &Request,
) -> Result<Value, Value> {
    let binding = request.binding.as_ref();
    let task_id = request
        .task_id
        .as_deref()
        .or_else(|| binding.map(|binding| binding.task_id.as_str()))
        .expect("validated bind task_id");
    let client_id = request
        .client_id
        .as_deref()
        .or_else(|| binding.map(|binding| binding.client_id.as_str()))
        .expect("validated bind client_id");
    let mut index = load_index(handoff, identity)?
        .ok_or_else(|| error("handoff_disabled", "handoff is not enabled"))?;
    if !index.enabled {
        return Err(error("handoff_disabled", "handoff is not enabled"));
    }
    if !index.tasks.iter().any(|summary| summary.task_id == task_id) {
        return Err(error("task_not_found", "task does not exist"));
    }
    if let Some(expected) = request.expected_revision {
        if expected != index.revision {
            return Err(revision_conflict(expected, index.revision));
        }
    }
    reject_retired_binding(&index, client_id)?;
    index
        .bindings
        .insert(client_id.to_string(), task_id.to_string());
    index.revision = next_revision(index.revision)?;
    index.updated_at = now_unix();
    let index_bytes = serialize_index(&index)?;
    let task_bytes = read_existing_task_bytes(handoff, task_id)?;
    check_total_capacity(handoff, &index, task_id, &task_bytes, None)?;
    atomic_write(handoff, INDEX_FILE_NAME, &index_bytes, true)?;
    Ok(json!({
        "status": "bound",
        "task_id": task_id,
        "client_id": client_id,
        "bound_task_id": task_id,
        "revision": index.revision,
    }))
}

#[cfg(unix)]
fn reject_retired_binding(index: &IndexFile, client_id: &str) -> Result<(), Value> {
    if index
        .bindings
        .get(client_id)
        .is_some_and(|id| index.retired_tasks.iter().any(|task| &task.task_id == id))
    {
        return Err(error(
            "task_archived",
            "this client belongs to an archived task; use a new session",
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn archive_task(
    handoff: &HandoffDir,
    identity: &ProjectIdentity,
    request: &Request,
    server_coordinated: bool,
) -> Result<Value, Value> {
    let task_id = request.task_id.as_deref().expect("validated task");
    let mut index = load_index(handoff, identity)?
        .ok_or_else(|| error("handoff_disabled", "handoff is not enabled"))?;
    if !index.enabled {
        return Err(error("handoff_disabled", "handoff is not enabled"));
    }
    if !index
        .tasks
        .iter()
        .chain(&index.retired_tasks)
        .any(|t| t.task_id == task_id)
    {
        return Err(error("task_not_found", "task does not exist"));
    }
    let task = load_task(handoff, identity, task_id)?;
    let expected = request.expected_revision.expect("validated revision");
    if task.revision != expected {
        return Err(revision_conflict(expected, task.revision));
    }
    if !server_coordinated
        && index
            .bindings
            .iter()
            .any(|(client, id)| id == task_id && client.starts_with("webcodex:"))
    {
        return Err(error(
            "server_retirement_required",
            "archive this task through its Server to check undelivered facts",
        ));
    }
    if task.status != "completed"
        || task.unknown_count != 0
        || job_projection(&task)
            .iter()
            .any(|job| job["terminal"] != true)
    {
        return Err(error(
            "task_unresolved",
            "task must be completed with no unknown or nonterminal work",
        ));
    }
    if index.retired_tasks.iter().any(|t| t.task_id == task_id) {
        return Ok(
            json!({"status":"archived","task_id":task_id,"revision":task.revision,"duplicate":true}),
        );
    }
    if index.retired_tasks.len() >= MAX_RETIRED_TASK_COUNT {
        return Err(error(
            "capacity_exceeded",
            "archived task capacity is full; history was retained",
        ));
    }
    // One atomic index replacement is the commit point. Task JSON, event
    // segments and user Markdown are untouched. v2 makes older writers fail closed.
    index.tasks.retain(|t| t.task_id != task_id);
    index.retired_tasks.push(task_summary_struct(&task));
    index.version = 2;
    index.revision = next_revision(index.revision)?;
    index.updated_at = now_unix();
    let mut history = index.clone();
    history.tasks = index.retired_tasks.clone();
    if total_capacity_bytes(handoff, &history, "", &[], None)? > MAX_RETIRED_BYTES {
        return Err(error(
            "capacity_exceeded",
            "archived history byte capacity is full",
        ));
    }
    atomic_write(handoff, INDEX_FILE_NAME, &serialize_index(&index)?, true)?;
    Ok(json!({"status":"archived","task_id":task_id,"revision":task.revision,"duplicate":false}))
}

#[cfg(unix)]
fn disable(
    handoff: &HandoffDir,
    identity: &ProjectIdentity,
    request: &Request,
) -> Result<Value, Value> {
    let Some(mut index) = load_index(handoff, identity)? else {
        return Ok(disabled_response());
    };
    if let Some(expected) = request.expected_revision {
        if expected != index.revision {
            return Err(revision_conflict(expected, index.revision));
        }
    }
    if !index.enabled {
        return Ok(disabled_response());
    }
    index.enabled = false;
    index.revision = next_revision(index.revision)?;
    index.updated_at = now_unix();
    let index_bytes = serialize_index(&index)?;
    atomic_write(handoff, INDEX_FILE_NAME, &index_bytes, true)?;
    Ok(json!({
        "status": "disabled",
        "enabled": false,
        "revision": index.revision,
    }))
}

#[cfg(unix)]
fn new_task(
    identity: &ProjectIdentity,
    task_id: &str,
    title: &str,
    event: Option<&NormalizedEvent>,
) -> TaskFile {
    let now = now_unix();
    let events = event
        .map(|event| vec![event.value.clone()])
        .unwrap_or_default();
    let unknown_count = event.map(|event| usize::from(event.unknown)).unwrap_or(0);
    let status = event
        .map(|event| next_task_status("active", event))
        .unwrap_or_else(|| "active".to_string());
    TaskFile {
        format: TASK_FORMAT.to_string(),
        version: 1,
        managed_by: MANAGED_BY.to_string(),
        project_identity: identity.clone(),
        task_id: task_id.to_string(),
        title: title.to_string(),
        status,
        revision: 1,
        created_at: now,
        updated_at: now,
        unknown_count,
        events,
        archives: Vec::new(),
        event_aliases: BTreeMap::new(),
    }
}

#[cfg(unix)]
fn apply_binding(index: &mut IndexFile, request: &Request, task_id: &str) -> Result<(), Value> {
    let client_id = request.client_id.as_deref().or_else(|| {
        request
            .binding
            .as_ref()
            .map(|binding| binding.client_id.as_str())
    });
    if let Some(client_id) = client_id {
        reject_retired_binding(index, client_id)?;
        index
            .bindings
            .insert(client_id.to_string(), task_id.to_string());
    }
    Ok(())
}

#[cfg(unix)]
fn next_task_status(current: &str, event: &NormalizedEvent) -> String {
    if let Some(status) = event.value.get("task_status").and_then(Value::as_str) {
        return status.to_string();
    }
    if event.unknown {
        return "unknown".to_string();
    }
    if matches!(
        event.value.get("type").and_then(Value::as_str),
        Some("task_completed")
    ) && event.value.get("status").and_then(Value::as_str) == Some("completed")
    {
        return "completed".to_string();
    }
    current.to_string()
}

#[cfg(unix)]
fn task_summary_struct(task: &TaskFile) -> TaskSummary {
    TaskSummary {
        task_id: task.task_id.clone(),
        title: task.title.clone(),
        status: task.status.clone(),
        revision: task.revision,
        updated_at: task.updated_at,
        event_count: task.events.len(),
        unknown_count: task.unknown_count,
    }
}

#[cfg(unix)]
fn task_summary(task: &TaskFile) -> Value {
    serde_json::to_value(task_summary_struct(task)).unwrap_or_else(|_| json!({}))
}

#[cfg(unix)]
fn capacity_output() -> Value {
    json!({
        "max_tasks": MAX_TASK_COUNT,
        "max_events_per_segment": MAX_EVENT_COUNT,
        "max_archives_per_task": MAX_ARCHIVE_COUNT,
        "max_events_per_task": MAX_EVENT_COUNT * (MAX_ARCHIVE_COUNT + 1),
        "max_task_bytes": MAX_TASK_BYTES,
        "max_total_bytes": MAX_TOTAL_BYTES,
    })
}

#[cfg(unix)]
fn serialize_index(index: &IndexFile) -> Result<Vec<u8>, Value> {
    let bytes = serde_json::to_vec_pretty(index)
        .map_err(|_| error("io_error", "handoff index cannot be serialized"))?;
    if bytes.len() > MAX_INDEX_BYTES {
        return Err(error(
            "capacity_exceeded",
            "handoff index exceeds its capacity limit",
        ));
    }
    Ok(bytes)
}

#[cfg(unix)]
fn archived_count(task: &TaskFile) -> usize {
    task.archives.iter().map(|a| a.event_count).sum()
}

#[cfg(unix)]
fn task_disk_view(task: &TaskFile) -> TaskFile {
    let mut view = task.clone();
    view.events = task.events[archived_count(task)..].to_vec();
    view
}

#[cfg(unix)]
fn validate_archive_reference(archive: &EventArchive, task_id: &str) -> Result<(), Value> {
    if archive.sha256.len() != 64
        || !archive
            .sha256
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        || archive.file != format!("{task_id}.events-{}.json", archive.sha256)
        || archive.event_count == 0
        || archive.event_count > MAX_EVENT_COUNT
        || archive.bytes > MAX_TASK_BYTES
    {
        return Err(error("malformed_task", "invalid archive reference"));
    }
    Ok(())
}

#[cfg(unix)]
fn plan_archive(task: &mut TaskFile) -> Result<Option<(String, Vec<u8>)>, Value> {
    let start = archived_count(task);
    if task.events.len() - start <= MAX_EVENT_COUNT && serialize_task(task).is_ok() {
        return Ok(None);
    }
    if task.archives.len() >= MAX_ARCHIVE_COUNT || task.events.len() <= start + 1 {
        return Err(error(
            "capacity_exceeded",
            "archive capacity reached; retain history and start a successor task",
        ));
    }
    // Archive only previously committed events. The name stays identical if
    // the process stops before updating the task and a different event retries.
    let events = &task.events[start..task.events.len() - 1];
    let bytes = serde_json::to_vec_pretty(events)
        .map_err(|_| error("io_error", "archive cannot be serialized"))?;
    if bytes.len() > MAX_TASK_BYTES {
        return Err(error("capacity_exceeded", "archive exceeds byte limit"));
    }
    let sha256 = format!("{:x}", Sha256::digest(&bytes));
    let file = format!("{}.events-{sha256}.json", task.task_id);
    task.archives.push(EventArchive {
        file: file.clone(),
        sha256,
        event_count: events.len(),
        bytes: bytes.len(),
    });
    Ok(Some((file, bytes)))
}

#[cfg(unix)]
fn serialize_task(task: &TaskFile) -> Result<Vec<u8>, Value> {
    let bytes = serde_json::to_vec_pretty(&task_disk_view(task))
        .map_err(|_| error("io_error", "task cannot be serialized"))?;
    if bytes.len() > MAX_TASK_BYTES {
        return Err(error(
            "capacity_exceeded",
            "task exceeds its capacity limit",
        ));
    }
    Ok(bytes)
}

#[cfg(unix)]
fn revision_conflict(expected: u64, actual: u64) -> Value {
    let mut output = error(
        "revision_conflict",
        "expected_revision does not match the current revision",
    );
    output["expected_revision"] = json!(expected);
    output["actual_revision"] = json!(actual);
    output
}

#[cfg(unix)]
fn next_revision(revision: u64) -> Result<u64, Value> {
    revision
        .checked_add(1)
        .ok_or_else(|| error("revision_exhausted", "revision cannot be incremented"))
}

#[cfg(unix)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct TargetMetadata {
    device: u64,
    inode: u64,
    nlink: u64,
    size: u64,
}

#[cfg(unix)]
fn target_metadata(handoff: &HandoffDir, name: &str) -> Result<Option<TargetMetadata>, Value> {
    use std::ffi::CString;
    use std::os::unix::io::RawFd;

    let Some(directory_fd) = handoff.fd() else {
        return Err(error("io_error", "handoff directory is not open"));
    };
    let cname =
        CString::new(name).map_err(|_| error("invalid_request", "handoff file name is invalid"))?;
    let mut stat = std::mem::MaybeUninit::<libc::stat>::uninit();
    let result = unsafe {
        libc::fstatat(
            directory_fd as RawFd,
            cname.as_ptr(),
            stat.as_mut_ptr(),
            libc::AT_SYMLINK_NOFOLLOW,
        )
    };
    if result != 0 {
        let io_error = std::io::Error::last_os_error();
        if io_error.kind() == std::io::ErrorKind::NotFound {
            return Ok(None);
        }
        if matches!(
            io_error.raw_os_error(),
            Some(code) if code == libc::ELOOP || code == libc::ENOTDIR
        ) {
            return Err(error("unsafe_path", "handoff target is not a regular file"));
        }
        return Err(error("io_error", "handoff target cannot be inspected"));
    }
    let stat = unsafe { stat.assume_init() };
    if stat.st_mode & libc::S_IFMT != libc::S_IFREG || stat.st_nlink != 1 {
        return Err(error(
            "unsafe_path",
            "handoff target must be a single-link regular file",
        ));
    }
    Ok(Some(TargetMetadata {
        device: stat.st_dev as u64,
        inode: stat.st_ino as u64,
        nlink: stat.st_nlink as u64,
        size: stat.st_size.max(0) as u64,
    }))
}

#[cfg(unix)]
fn read_existing_task_bytes(handoff: &HandoffDir, task_id: &str) -> Result<Vec<u8>, Value> {
    let name = task_file_name(task_id);
    read_file_bounded(handoff, &name, MAX_TASK_BYTES, "capacity_exceeded")?
        .ok_or_else(|| error("task_missing", "managed task file is missing"))
}

#[cfg(unix)]
struct MarkdownPlan {
    state: MarkdownState,
    bytes: Option<Vec<u8>>,
    original: Option<Vec<u8>>,
}

#[cfg(unix)]
impl MarkdownState {
    fn as_str(self) -> &'static str {
        match self {
            MarkdownState::Created => "created",
            MarkdownState::Updated => "updated",
            MarkdownState::PreservedUnmanaged => "preserved_unmanaged",
        }
    }
}

#[cfg(unix)]
fn markdown_plan(handoff: &HandoffDir, name: &str, task: &TaskFile) -> Result<MarkdownPlan, Value> {
    let existing = read_file_bounded(handoff, name, MAX_MARKDOWN_BYTES, "capacity_exceeded")?;
    let Some(existing) = existing else {
        return Ok(MarkdownPlan {
            state: MarkdownState::Created,
            bytes: Some(render_markdown(task).into_bytes()),
            original: None,
        });
    };
    let existing = String::from_utf8(existing)
        .map_err(|_| error("markdown_conflict", "managed Markdown is not UTF-8"))?;
    let start_count = existing.match_indices(MACHINE_START).count();
    let end_count = existing.match_indices(MACHINE_END).count();
    if start_count == 0 && end_count == 0 {
        return Ok(MarkdownPlan {
            state: MarkdownState::PreservedUnmanaged,
            bytes: None,
            original: Some(existing.into_bytes()),
        });
    }
    if start_count != 1 || end_count != 1 {
        return Err(error(
            "markdown_conflict",
            "managed Markdown machine markers are ambiguous",
        ));
    }
    let start = existing.find(MACHINE_START).expect("marker counted");
    let end = existing.find(MACHINE_END).expect("marker counted");
    if end < start {
        return Err(error(
            "markdown_conflict",
            "managed Markdown machine markers are inverted",
        ));
    }
    let end_after = end + MACHINE_END.len();
    let replacement = machine_region(task);
    let updated = format!(
        "{}{}{}",
        &existing[..start],
        replacement,
        &existing[end_after..]
    );
    if updated.len() > MAX_MARKDOWN_BYTES {
        return Err(error(
            "capacity_exceeded",
            "Markdown exceeds its capacity limit",
        ));
    }
    Ok(MarkdownPlan {
        state: MarkdownState::Updated,
        bytes: Some(updated.into_bytes()),
        original: Some(existing.into_bytes()),
    })
}

#[cfg(unix)]
fn render_markdown(task: &TaskFile) -> String {
    format!(
        "# {}\n\n{}\n\n{}\n\nHuman or agent notes go between the notes markers. They are preserved by WebCodex.\n{}\n",
        task.title,
        machine_region(task),
        NOTES_START,
        NOTES_END,
    )
}

#[cfg(unix)]
fn job_projection(task: &TaskFile) -> Vec<Value> {
    let mut jobs: BTreeMap<String, Value> = BTreeMap::new();
    for event in &task.events {
        let Some(id) = event["job_id"].as_str() else {
            continue;
        };
        let terminal = event["type"] == "job_terminal";
        let replace = jobs.get(id).is_none_or(|old| {
            if old["terminal"] == true && !terminal {
                return false;
            }
            terminal && old["terminal"] != true
                || event["job_update_seq"].as_u64().unwrap_or(0)
                    >= old["job_update_seq"].as_u64().unwrap_or(0)
        });
        if replace {
            jobs.insert(id.into(), json!({"job_id":id,"status":event["status"],"terminal":terminal,
            "exit_code":event["exit_code"],"job_update_seq":event["job_update_seq"],"source":event["source"]}));
        }
    }
    jobs.into_values().collect()
}

#[cfg(unix)]
fn machine_region(task: &TaskFile) -> String {
    let latest_event = task.events.last().and_then(|event| {
        Some(json!({
            "event_id": event.get("event_id")?,
            "type": event.get("type")?,
            "source": event.get("source").cloned().unwrap_or(Value::Null),
            "status": event.get("status").cloned().unwrap_or(Value::Null),
            "outcome": event.get("outcome").cloned().unwrap_or(Value::Null),
            "summary": event.get("summary").and_then(Value::as_str).map(|summary| truncate_chars(summary, 240)),
            "unknown": event.get("unknown").cloned().unwrap_or(Value::Bool(false)),
        }))
    });
    let jobs = job_projection(task);
    let machine = json!({
        "task_id": task.task_id,
        "revision": task.revision,
        "status": task.status,
        "event_count": task.events.len(),
        "unknown_count": task.unknown_count,
        "updated_at": task.updated_at,
        "latest_event": latest_event,
        "jobs": jobs.iter().take(MAX_EVENT_COUNT).collect::<Vec<_>>(),
        "jobs_total": jobs.len(),
        "jobs_truncated": jobs.len() > MAX_EVENT_COUNT,
        "history_files": task.archives.iter().map(|a| format!("handoff/{}", a.file)).collect::<Vec<_>>(),
    });
    format!(
        "{}\n{}\n{}",
        MACHINE_START,
        serde_json::to_string(&machine).unwrap_or_else(|_| "{}".to_string()),
        MACHINE_END
    )
}

#[cfg(unix)]
fn truncate_chars(value: &str, max: usize) -> String {
    value.chars().take(max).collect()
}

#[cfg(unix)]
fn check_total_capacity(
    handoff: &HandoffDir,
    index: &IndexFile,
    target_task_id: &str,
    target_task_bytes: &[u8],
    target_markdown_bytes: Option<&[u8]>,
) -> Result<(), Value> {
    let total = total_capacity_bytes(
        handoff,
        index,
        target_task_id,
        target_task_bytes,
        target_markdown_bytes,
    )?;
    if total > MAX_TOTAL_BYTES {
        return Err(error(
            "capacity_exceeded",
            "handoff storage exceeds its total capacity",
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn total_capacity_bytes(
    handoff: &HandoffDir,
    index: &IndexFile,
    target_task_id: &str,
    target_task_bytes: &[u8],
    target_markdown_bytes: Option<&[u8]>,
) -> Result<usize, Value> {
    let mut total = serialize_index(index)?.len();
    for summary in &index.tasks {
        let stored = if summary.task_id == target_task_id {
            target_task_bytes.to_vec()
        } else {
            read_existing_task_bytes(handoff, &summary.task_id)?
        };
        let stored_len = stored.len();
        let stored: TaskFile = serde_json::from_slice(&stored)
            .map_err(|_| error("malformed_task", "task cannot be counted"))?;
        for archive in &stored.archives {
            validate_archive_reference(archive, &summary.task_id)?;
            total = total.saturating_add(archive.bytes);
        }
        total = total.saturating_add(stored_len);
        let markdown_name = markdown_file_name(&summary.task_id);
        if summary.task_id == target_task_id {
            if let Some(bytes) = target_markdown_bytes {
                total = total.saturating_add(bytes.len());
            }
        } else if let Some(bytes) = read_file_bounded(
            handoff,
            &markdown_name,
            MAX_MARKDOWN_BYTES,
            "capacity_exceeded",
        )? {
            let text = String::from_utf8(bytes)
                .map_err(|_| error("markdown_conflict", "managed Markdown is not UTF-8"))?;
            if text.contains(MACHINE_START) && text.contains(MACHINE_END) {
                total = total.saturating_add(text.len());
            }
        }
    }
    Ok(total)
}

#[cfg(unix)]
fn atomic_write(
    handoff: &HandoffDir,
    name: &str,
    bytes: &[u8],
    replace_existing: bool,
) -> Result<(), Value> {
    atomic_write_checked(handoff, name, bytes, replace_existing, None)
}

#[cfg(unix)]
fn atomic_write_checked(
    handoff: &HandoffDir,
    name: &str,
    bytes: &[u8],
    replace_existing: bool,
    expected_contents: Option<Option<&[u8]>>,
) -> Result<(), Value> {
    if bytes.len() > MAX_INDEX_BYTES && name == INDEX_FILE_NAME {
        return Err(error(
            "capacity_exceeded",
            "handoff index exceeds its capacity limit",
        ));
    }
    let before = target_metadata(handoff, name)?;
    let original = read_file_bounded(handoff, name, MAX_TASK_BYTES, "capacity_exceeded")?;
    if expected_contents.is_some_and(|expected| expected != original.as_deref()) {
        return Err(error(
            "markdown_conflict",
            "handoff content changed since it was read",
        ));
    }
    if before.is_some() && !replace_existing {
        return Err(error("non_managed_file", "handoff target already exists"));
    }
    let temp_name = format!(".{}.tmp-{}", name, uuid::Uuid::new_v4().simple());
    let result = (|| {
        let mut file = open_at(handoff, &temp_name, true)?
            .ok_or_else(|| error("io_error", "handoff temporary file cannot be created"))?;
        use std::io::Write;
        file.write_all(bytes)
            .map_err(|_| error("io_error", "handoff temporary file cannot be written"))?;
        file.sync_all()
            .map_err(|_| error("io_error", "handoff temporary file cannot be synced"))?;
        drop(file);

        let after = target_metadata(handoff, name)?;
        if read_file_bounded(handoff, name, MAX_TASK_BYTES, "capacity_exceeded")? != original {
            return Err(error(
                "concurrent_modification",
                "handoff content changed while writing",
            ));
        }
        match (before, after) {
            (None, None) => {}
            (Some(before), Some(after))
                if replace_existing
                    && before.device == after.device
                    && before.inode == after.inode
                    && before.nlink == 1
                    && after.nlink == 1 => {}
            (None, Some(_)) if !replace_existing => {
                return Err(error(
                    "non_managed_file",
                    "handoff target appeared while writing",
                ));
            }
            (Some(_), None) | (None, Some(_)) | (Some(_), Some(_)) => {
                return Err(error("unsafe_path", "handoff target changed while writing"));
            }
        }

        rename_at(handoff, &temp_name, name)?;
        if let Err(err) = sync_directory_handle(handoff) {
            return Err(mark_state_changed(err));
        }
        Ok(())
    })();
    if result.is_err() {
        if remove_file_at(handoff, &temp_name) {
            return result.map_err(mark_state_changed);
        }
    }
    result
}

#[cfg(unix)]
fn rename_at(handoff: &HandoffDir, source: &str, target: &str) -> Result<(), Value> {
    use std::ffi::CString;
    let Some(directory_fd) = handoff.fd() else {
        return Err(error("io_error", "handoff directory is not open"));
    };
    let source = CString::new(source)
        .map_err(|_| error("invalid_request", "handoff source name is invalid"))?;
    let target = CString::new(target)
        .map_err(|_| error("invalid_request", "handoff target name is invalid"))?;
    let result =
        unsafe { libc::renameat(directory_fd, source.as_ptr(), directory_fd, target.as_ptr()) };
    if result != 0 {
        return Err(error("io_error", "handoff file cannot be replaced"));
    }
    Ok(())
}

/// Remove a temporary or a create-time rollback file relative to the opened
/// handoff directory.  The boolean reports a cleanup failure so callers can
/// expose that a previous durable write may still be present.
#[cfg(unix)]
fn remove_file_at(handoff: &HandoffDir, name: &str) -> bool {
    use std::ffi::CString;
    let Some(directory_fd) = handoff.fd() else {
        return true;
    };
    let Ok(name) = CString::new(name) else {
        return true;
    };
    let result = unsafe { libc::unlinkat(directory_fd, name.as_ptr(), 0) };
    if result == 0 {
        return false;
    }
    std::io::Error::last_os_error().kind() != std::io::ErrorKind::NotFound
}

#[cfg(unix)]
fn now_unix() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs().min(i64::MAX as u64) as i64)
        .unwrap_or(0)
}

#[cfg(all(test, unix))]
#[path = "handoff_checkpoint/tests.rs"]
mod tests;
