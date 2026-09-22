use super::*;
use crate::project_handoff_job::{prepare, record, HandoffTarget};
use serde_json::json;
use sha2::{Digest, Sha256};
use webcodex_workspace::handoff_checkpoint::execute;

fn fixture() -> (tempfile::TempDir, PathBuf, PathBuf, ShellJobSnapshot) {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("project");
    let registry = tmp.path().join("registry");
    std::fs::create_dir(&root).unwrap();
    std::fs::create_dir(&registry).unwrap();
    let root = root.canonicalize().unwrap();
    std::fs::write(
        registry.join("demo.v1.toml"),
        format!(
            "id = \"demo.v1\"\npath = {:?}\nallow_patch = true\n",
            root.to_str().unwrap()
        ),
    )
    .unwrap();
    execute(
        &root,
        json!({"action":"create","task_id":"task-a","title":"Fixture"}),
    )
    .unwrap();
    let mut job = test_job_snapshot("job-one");
    job.status = "runner_queued".into();
    job.started_at = None;
    job.context.runtime_project_id = Some("agent:test:demo.v1".into());
    job.context.project_cwd = Some(root.to_str().unwrap().into());
    job.context.workflow_session_id = Some("wc_sess_fixture".into());
    job.context.command_preview = "private command must not be persisted".into();
    let actor = format!("webcodex:{:x}", Sha256::digest(b"wc_sess_fixture"));
    execute(
        &root,
        json!({"action":"bind","task_id":"task-a","client_id":actor}),
    )
    .unwrap();
    (tmp, root, registry, job)
}

#[test]
fn handoff_job_terminal_persists_without_server_or_model_call() {
    let (_tmp, root, registry, job) = fixture();
    let target = prepare_for(&registry, &root, &job.context).unwrap();
    let manager = JobManager::new(1);
    crate::lock_unpoison(&manager.jobs).insert(
        job.job_id.clone(),
        RunningJob {
            handoff_target: Some(target),
            client_id: "test".into(),
            runner_instance_id: "fixture".into(),
            snapshot: job,
            child: None,
            stop_requested: std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false)),
            slot_reserved: false,
        },
    );
    let (running, running_semantic) = manager
        .record_update(
            "job-one",
            RunnerJobDelta {
                status: "running".into(),
                ..Default::default()
            },
        )
        .unwrap();
    let (terminal, terminal_semantic) = manager
        .record_update(
            "job-one",
            RunnerJobDelta {
                status: "failed".into(),
                exit_code: Some(7),
                finished: true,
                ..Default::default()
            },
        )
        .unwrap();
    // Both updates have committed before either checkpoint callback runs.
    // Recording must retain each exact update, not read the newest status twice.
    manager.queue_recorded_update(running, running_semantic);
    manager.queue_recorded_update(terminal, terminal_semantic);
    manager.resend_snapshot("job-one");
    let saved = execute(&root, json!({"action":"read","task_id":"task-a"})).unwrap();
    let events = saved["checkpoint"]["events"].as_array().unwrap();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0]["status"], "running");
    assert_eq!(events[1]["job_id"], "job-one");
    assert_eq!(events[1]["status"], "failed");
    assert_eq!(events[1]["exit_code"], 7);
    assert!(!saved.to_string().contains("private command"));
}

#[test]
fn handoff_job_rebinding_cannot_retarget_inflight_job() {
    let (_tmp, root, registry, job) = fixture();
    let target = prepare_for(&registry, &root, &job.context).unwrap();
    execute(
        &root,
        json!({"action":"create","task_id":"task-b","title":"Other"}),
    )
    .unwrap();
    let actor = format!("webcodex:{:x}", Sha256::digest(b"wc_sess_fixture"));
    execute(
        &root,
        json!({"action":"bind","task_id":"task-b","client_id":actor}),
    )
    .unwrap();
    assert!(record(&target, "test", &job).is_err());
    let other = execute(&root, json!({"action":"read","task_id":"task-b"})).unwrap();
    assert!(other["checkpoint"]["events"].as_array().unwrap().is_empty());
}

#[test]
fn handoff_job_revoked_project_write_does_not_save() {
    let (_tmp, root, registry, job) = fixture();
    let target = prepare_for(&registry, &root, &job.context).unwrap();
    std::fs::write(
        registry.join("demo.v1.toml"),
        format!(
            "id = \"demo.v1\"\npath = {:?}\nallow_patch = false\n",
            root.to_str().unwrap()
        ),
    )
    .unwrap();
    assert!(record(&target, "test", &job).is_err());
    let saved = execute(&root, json!({"action":"read","task_id":"task-a"})).unwrap();
    assert!(saved["checkpoint"]["events"].as_array().unwrap().is_empty());
}

fn prepare_for(registry: &Path, root: &Path, context: &ShellJobContext) -> Option<HandoffTarget> {
    prepare(
        registry,
        "test",
        &crate::RunnerPolicy {
            allowed_roots: vec![root.to_path_buf()],
            ..Default::default()
        },
        context,
    )
}

#[test]
fn handoff_job_relative_wire_root_resolves_exact_registration() {
    let (_tmp, root, registry, mut job) = fixture();
    job.context.project_cwd = Some(".".into());
    let target = prepare_for(&registry, &root, &job.context).unwrap();
    job.status = "failed".into();
    job.exit_code = Some(7);
    record(&target, "test", &job).unwrap();
    let saved = execute(&root, json!({"action":"read","task_id":"task-a"})).unwrap();
    assert_eq!(saved["checkpoint"]["events"][0]["exit_code"], 7);
    assert_eq!(saved["checkpoint"]["events"][0]["job_id"], job.job_id);
    assert!(prepare(
        &registry,
        "other",
        &crate::RunnerPolicy::default(),
        &job.context
    )
    .is_none());
    assert!(prepare(
        &registry,
        "test",
        &crate::RunnerPolicy::default(),
        &job.context
    )
    .is_none());
    for wrong in ["..", "subdir", "/different/project"] {
        job.context.project_cwd = Some(wrong.into());
        assert!(prepare_for(&registry, &root, &job.context).is_none());
    }
}

#[test]
fn handoff_job_relative_root_cannot_follow_registration_retarget() {
    let (tmp, root, registry, mut job) = fixture();
    job.context.project_cwd = Some(".".into());
    let target = prepare_for(&registry, &root, &job.context).unwrap();
    let other = tmp.path().join("other");
    std::fs::create_dir(&other).unwrap();
    std::fs::write(
        registry.join("demo.v1.toml"),
        format!(
            "id = \"demo.v1\"\npath = {:?}\nallow_patch = true\n",
            other.to_str().unwrap()
        ),
    )
    .unwrap();
    assert!(record(&target, "test", &job).is_err());
    assert!(!other.join("handoff").exists());
    let saved = execute(&root, json!({"action":"read","task_id":"task-a"})).unwrap();
    assert!(saved["checkpoint"]["events"].as_array().unwrap().is_empty());
}

#[test]
fn handoff_job_registration_uses_runner_defaults_and_rejects_malformed_policy() {
    let (_tmp, root, registry, mut job) = fixture();
    job.context.project_cwd = Some(".".into());
    let header = format!("id = \"demo.v1\"\npath = {:?}\n", root.to_str().unwrap());
    std::fs::write(registry.join("demo.v1.toml"), &header).unwrap();
    assert!(prepare_for(&registry, &root, &job.context).is_some());
    for policy in [
        "disabled = true\n",
        "disabled = \"false\"\n",
        "allow_patch = \"true\"\n",
    ] {
        std::fs::write(registry.join("demo.v1.toml"), format!("{header}{policy}")).unwrap();
        assert!(prepare_for(&registry, &root, &job.context).is_none());
    }
}
