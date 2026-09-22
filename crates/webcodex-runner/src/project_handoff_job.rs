//! Runner-owned Job facts reach the same local checkpoint without a later
//! model call or a live Server connection. Only explicit local task bindings
//! and an existing writable project registration allow this bookkeeping.
use crate::runner_protocol::{ShellJobContext, ShellJobSnapshot};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::Read;
use std::path::{Path, PathBuf};
use webcodex_workspace::handoff_checkpoint::execute;

#[derive(Debug, Clone)]
pub(crate) struct HandoffTarget {
    registry: PathBuf,
    root: PathBuf,
    task_id: String,
    root_fingerprint: String,
}

pub(crate) fn prepare(
    registry: &Path,
    client: &str,
    policy: &crate::RunnerPolicy,
    context: &ShellJobContext,
) -> Option<HandoffTarget> {
    let root = registered_root(registry, client, context).ok()?;
    crate::webcodex_runner::shell::cwd_allowed(policy, &root).ok()?;
    let session = context.workflow_session_id.as_deref()?;
    let actor = format!("webcodex:{:x}", Sha256::digest(session.as_bytes()));
    let state = execute(&root, json!({"action":"status","client_id":actor})).ok()?;
    if state["enabled"] != true {
        return None;
    }
    let task = state["bound_task_id"].as_str()?;
    let current = execute(&root, json!({"action":"read","task_id":task})).ok()?;
    Some(HandoffTarget {
        registry: registry.to_path_buf(),
        root,
        task_id: task.into(),
        root_fingerprint: current
            .pointer("/checkpoint/project_identity/root_fingerprint")?
            .as_str()?
            .into(),
    })
}

pub(crate) fn record(
    target: &HandoffTarget,
    client: &str,
    snapshot: &ShellJobSnapshot,
) -> Result<(), ()> {
    let context = &snapshot.context;
    let root = registered_root(&target.registry, client, context)?;
    if root != target.root {
        return Err(());
    }
    let session = context.workflow_session_id.as_deref().ok_or(())?;
    let actor = format!("webcodex:{:x}", Sha256::digest(session.as_bytes()));
    let state = execute(&root, json!({"action":"status","client_id":actor})).map_err(|_| ())?;
    let task = target.task_id.as_str();
    if state["enabled"] != true || state["bound_task_id"].as_str() != Some(task) {
        return Err(());
    }
    let mut event = json!({
        "event_id":format!("runner-job-{:x}", Sha256::digest(format!("{}:{}",snapshot.job_id,snapshot.update_seq))),
        "type":if webcodex_core::runner_job_lifecycle::RunnerJobLifecycle::from_wire(&snapshot.status).is_ok_and(webcodex_core::runner_job_lifecycle::RunnerJobLifecycle::is_terminal) { "job_terminal" } else { "job_started" },
        "source":"runner", "job_id":snapshot.job_id,"status":snapshot.status,"job_update_seq":snapshot.update_seq,
    });
    if let Some(code) = snapshot.exit_code {
        event["exit_code"] = code.into();
    }
    for attempt in 0..2 {
        let current = execute(&root, json!({"action":"read","task_id":task})).map_err(|_| ())?;
        if current
            .pointer("/checkpoint/project_identity/root_fingerprint")
            .and_then(Value::as_str)
            != Some(target.root_fingerprint.as_str())
        {
            return Err(());
        }
        let revision = current["revision"].as_u64().ok_or(())?;
        match execute(
            &root,
            json!({"action":"append","task_id":task,"expected_revision":revision,"event":event}),
        ) {
            Ok(_) => return Ok(()),
            Err(error) if attempt == 0 && error["code"] == "revision_conflict" => continue,
            Err(_) => return Err(()),
        }
    }
    Err(())
}

fn registered_root(
    registry: &Path,
    client: &str,
    context: &ShellJobContext,
) -> Result<PathBuf, ()> {
    if context.ssh_resource.is_some() {
        return Err(());
    }
    let prefix = format!("agent:{client}:");
    let id = context
        .runtime_project_id
        .as_deref()
        .and_then(|id| id.strip_prefix(&prefix))
        .ok_or(())?;
    if id.is_empty()
        || id.len() > 250
        || matches!(id, "." | "..")
        || !id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-' | b'.'))
    {
        return Err(());
    }
    let path = registry.join(format!("{id}.toml"));
    if !std::fs::symlink_metadata(&path).map_err(|_| ())?.is_file() {
        return Err(());
    }
    let mut content = String::new();
    std::fs::File::open(&path)
        .map_err(|_| ())?
        .take(65537)
        .read_to_string(&mut content)
        .map_err(|_| ())?;
    if content.len() > 65536 {
        return Err(());
    }
    let registration: crate::webcodex_runner::projects::RunnerProjectFile =
        toml::from_str(&content).map_err(|_| ())?;
    if registration.id != id || !registration.allow_patch || registration.disabled {
        return Err(());
    }
    let root = PathBuf::from(registration.path);
    if !root.is_absolute() {
        return Err(());
    }
    // Job context carries a project-relative root marker on the real wire.
    // Resolve only through its exact registered identity, never Runner cwd.
    match context.project_cwd.as_deref() {
        Some(".") => {}
        Some(path) if Path::new(path) == root => {}
        _ => return Err(()),
    }
    Ok(root)
}
