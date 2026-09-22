//! In-process transport tests: real registry and checkpoint filesystem, no socket.
use super::support::*;
use crate::runner_protocol::{RunnerCapabilities, RunnerRegisterRequest};
use crate::tool_runtime::{ToolCall, ToolRuntime};
use serde_json::{json, Value};
use std::path::Path;
use std::sync::Arc;

async fn fixture() -> (tempfile::TempDir, Arc<ToolRuntime>, String) {
    let tmp = tempfile::tempdir().unwrap();
    let runtime = Arc::new(test_runtime().with_project_handoff_database(Arc::new(
        crate::Database::open(&tmp.path().join("state.db")).unwrap(),
    )));
    let root = tmp.path().join("project");
    std::fs::create_dir(&root).unwrap();
    let auth = auth_context(Some("handoff-user"), false);
    let id = register_handoff_project(&runtime, "handoff", "p", &root, &auth).await;
    let access = crate::test_support::runner_access(&auth);
    assert!(runtime
        .runner_registry
        .runner_supports_for_auth("handoff", "project_handoff", Some(&access))
        .await
        .unwrap());
    (tmp, runtime, id)
}

async fn reply(runtime: &ToolRuntime, root: &std::path::Path, malformed: bool) {
    let request = wait_for_patch_agent_request(runtime, "handoff").await;
    assert!(matches!(
        request.kind.as_str(),
        "file_handoff_read" | "file_handoff_write"
    ));
    let body: Value = serde_json::from_str(request.content.as_deref().unwrap()).unwrap();
    let (code, value) = if malformed {
        (
            0,
            json!({"success":true,"output":{"status":"saved","task_id":"wrong","event_id":"wrong","revision":2}}),
        )
    } else {
        match webcodex_workspace::handoff_checkpoint::execute_from_runner(root, body) {
            Ok(output) => (0, json!({"success":true,"output":output})),
            Err(error) => (1, json!({"success":false,"error":error})),
        }
    };
    complete_patch_agent_request(
        runtime,
        "handoff",
        &request.request_id,
        code,
        &value.to_string(),
        "",
    )
    .await;
}

#[tokio::test]
async fn project_handoff_unbound_admission_is_read_only_and_blocks_execution() {
    let (tmp, runtime, id) = fixture().await;
    let root = tmp.path().join("project");
    webcodex_workspace::handoff_checkpoint::execute(
        &root,
        json!({"action":"create","task_id":"a","title":"Task"}),
    )
    .unwrap();
    let auth = auth_context(Some("handoff-user"), false);
    let resolved = runtime
        .resolve_project_input_for_auth(&id, Some(&auth))
        .await
        .unwrap();
    let (result, ()) = tokio::join!(
        runtime.handoff_admission(&resolved, None, Some(&auth)),
        reply(&runtime, &root, false)
    );
    let denied = result.unwrap_err();
    assert_eq!(denied.output["execution_state"], "not_started");
    let saved = webcodex_workspace::handoff_checkpoint::execute(
        &root,
        json!({"action":"read","task_id":"a"}),
    )
    .unwrap();
    assert_eq!(saved["revision"], 1);
}

#[tokio::test]
async fn project_handoff_disabled_admission_preserves_legacy_behavior() {
    let (tmp, runtime, id) = fixture().await;
    let root = tmp.path().join("project");
    let auth = auth_context(Some("handoff-user"), false);
    let resolved = runtime
        .resolve_project_input_for_auth(&id, Some(&auth))
        .await
        .unwrap();
    let (result, ()) = tokio::join!(
        runtime.handoff_admission(&resolved, None, Some(&auth)),
        reply(&runtime, &root, false)
    );
    result.unwrap();
    assert!(!root.join("handoff").exists());
}

#[tokio::test]
async fn project_handoff_wrong_append_ack_remains_unknown() {
    let (tmp, runtime, id) = fixture().await;
    let root = tmp.path().join("project");
    let auth = auth_context(Some("handoff-user"), false);
    let resolved = runtime
        .resolve_project_input_for_auth(&id, Some(&auth))
        .await
        .unwrap();
    let (result,())=tokio::join!(runtime.handoff_runner_request(&resolved,true,
        json!({"action":"append","task_id":"a","expected_revision":1,"event":{"event_id":"e","type":"note_added","source":"gpt"}}),Some(&auth)),reply(&runtime,&root,true));
    assert_eq!(result.unwrap_err(), "handoff_save_unknown");
}

#[tokio::test]
async fn project_handoff_read_does_not_need_old_session_and_exposes_pending() {
    let (tmp, runtime, id) = fixture().await;
    let root = tmp.path().join("project");
    webcodex_workspace::handoff_checkpoint::execute(
        &root,
        json!({"action":"create","task_id":"a","title":"Task"}),
    )
    .unwrap();
    let auth = auth_context(Some("handoff-user"), false);
    let read = runtime.dispatch_project_handoff(
        ToolCall::ProjectHandoffRead {
            project: id,
            task_id: Some("a".into()),
            session_id: None,
        },
        Some(&auth),
    );
    let (result, ()) = tokio::join!(read, reply(&runtime, &root, false));
    assert!(result.success);
    assert_eq!(result.output["source_status"]["status"], "unbound");
    assert_eq!(result.output["revision"], 1);
}

async fn register_handoff_project(
    runtime: &ToolRuntime,
    client_id: &str,
    project_id: &str,
    root: &Path,
    auth: &crate::auth::AuthContext,
) -> String {
    let project_path = root.to_string_lossy().to_string();
    runtime
        .runner_registry
        .register_with_auth(
            RunnerRegisterRequest {
                process_started_at: None,
                build: None,
                job_concurrency_limit: None,
                job_inventory: None,
                coding_agent_providers: None,
                coding_agent_inventory: None,
                client_id: client_id.to_string(),
                runner_instance_id: "inst".to_string(),
                runner_protocol_generation: crate::runner_protocol::RUNNER_PROTOCOL_GENERATION_V2,
                display_name: None,
                owner: auth.username.clone(),
                hostname: None,
                host_context: None,
                capabilities: crate::test_support::current_runner_capabilities(
                    RunnerCapabilities {
                        project_handoff: true,
                        shell: true,
                        git: true,
                        file_read: true,
                        file_write: true,
                        internal_posix_script: true,
                        ..Default::default()
                    },
                ),
                policy: None,
            },
            Some(&crate::test_support::runner_access(auth)),
        )
        .await
        .unwrap();
    crate::test_support::apply_project_inventory_snapshot(
        &runtime.runner_registry,
        client_id,
        "inst",
        vec![named_registered_project(
            client_id,
            project_id,
            project_id,
            &project_path,
            1,
        )],
    )
    .await;
    crate::tool_runtime::runner_project_runtime_id(client_id, project_id)
}

#[tokio::test]
async fn project_handoff_malformed_discovery_cannot_disable_admission() {
    let (tmp, runtime, id) = fixture().await;
    let root = tmp.path().join("project");
    let auth = auth_context(Some("handoff-user"), false);
    let resolved = runtime
        .resolve_project_input_for_auth(&id, Some(&auth))
        .await
        .unwrap();
    let (result, ()) = tokio::join!(
        runtime.handoff_admission(&resolved, None, Some(&auth)),
        reply(&runtime, &root, true)
    );
    assert!(result.is_err());
    assert!(!root.join("handoff").exists());
}

#[tokio::test]
async fn project_handoff_capture_preserves_job_failure_and_marks_partial_paths() {
    let (tmp, runtime, id) = fixture().await;
    let session = runtime.sessions.start_session(Some(id.clone()), None);
    let db = runtime.project_handoff_db.as_ref().unwrap();
    db.handoff_bind(&crate::db::HandoffBinding {
        session_id: session.session_id.clone(),
        project_id: id.clone(),
        client_id: "handoff".into(),
        project_path: tmp.path().join("project").to_str().unwrap().into(),
        task_id: "task-a".into(),
        root_fingerprint: "a".repeat(64),
    })
    .unwrap();
    let mut start = runtime
        .sessions
        .record_tool_call_started_with_options(
            Some(&session.session_id),
            crate::tool_runtime::sessions::SessionTransport::Api,
            "apply_text_edits",
            &json!({"project":id}),
            Some(id),
            crate::tool_runtime::sessions::session_tool_contract("apply_text_edits"),
        )
        .unwrap();
    start.changed_paths = (0..40).map(|i| format!("file-{i}.md")).collect();
    let result = crate::tool_runtime::ToolResult::err_with_output(
        "fixture failure",
        json!({"exit_code":7,"job_id":"original-job","stdout":"do-not-store"}),
    );
    assert_eq!(
        runtime.capture_handoff_fact(Some(&start), &result).unwrap()["status"],
        "pending"
    );
    let saved = db.handoff_pending(&session.session_id).unwrap();
    assert_eq!(saved.len(), 1);
    assert_eq!(saved[0].event["exit_code"], 7);
    assert_eq!(saved[0].event["success"], false);
    assert_eq!(saved[0].event["job_id"], "original-job");
    assert_eq!(saved[0].event["paths"].as_array().unwrap().len(), 32);
    assert_eq!(saved[0].event["unknown"], true);
    assert_eq!(saved[0].event["status"], "partial_path_coverage");
    assert!(!saved[0].event.to_string().contains("do-not-store"));
    start.logical_invocation_role = Some("recorder".into());
    assert!(runtime
        .capture_handoff_fact(Some(&start), &result)
        .is_none());
    assert_eq!(db.handoff_pending(&session.session_id).unwrap().len(), 1);
}

#[tokio::test]
async fn project_handoff_archive_roundtrip_preserves_read_and_retires_binding() {
    let (tmp, runtime, id) = fixture().await;
    let root = tmp.path().join("project");
    let original = webcodex_workspace::handoff_checkpoint::execute(&root,
        json!({"action":"create","task_id":"done","title":"Done","event":{"event_id":"finished","type":"task_completed","source":"gpt","status":"completed"}})).unwrap();
    assert_eq!(original["revision"], 1);
    let checkpoint = webcodex_workspace::handoff_checkpoint::execute(
        &root,
        json!({"action":"read","task_id":"done"}),
    )
    .unwrap();
    let b = crate::db::HandoffBinding {
        session_id: "old".into(),
        project_id: id.clone(),
        client_id: "handoff".into(),
        project_path: root.to_str().unwrap().into(),
        task_id: "done".into(),
        root_fingerprint: checkpoint["checkpoint"]["project_identity"]["root_fingerprint"]
            .as_str()
            .unwrap()
            .into(),
    };
    let db = runtime.project_handoff_db.as_ref().unwrap();
    db.handoff_bind(&b).unwrap();
    webcodex_workspace::handoff_checkpoint::execute(&root,json!({"action":"bind","task_id":"done","client_id":crate::tool_runtime::project_handoff::client_key("old")})).unwrap();
    let auth = auth_context(Some("handoff-user"), false);
    let resolved = runtime
        .resolve_project_input_for_auth(&id, Some(&auth))
        .await
        .unwrap();
    let request: webcodex_tool_contracts::ProjectHandoffRequest =
        serde_json::from_value(json!({"action":"archive","task_id":"done","expected_revision":1}))
            .unwrap();
    {
        let _active = runtime.handoff_retirement_gate.read().await;
        let blocked = runtime
            .dispatch_project_handoff(
                ToolCall::ProjectHandoffWrite {
                    project: id.clone(),
                    session_id: "old".into(),
                    request: request.clone(),
                },
                Some(&auth),
            )
            .await;
        assert!(!blocked.success);
        assert!(!db.handoff_retirement_started(&b).unwrap());
    }
    let (unknown, ()) = tokio::join!(
        runtime.dispatch_project_handoff(
            ToolCall::ProjectHandoffWrite {
                project: id.clone(),
                session_id: "old".into(),
                request: request.clone()
            },
            Some(&auth)
        ),
        async {
            reply(&runtime, &root, false).await;
            reply(&runtime, &root, true).await;
        }
    );
    assert!(!unknown.success);
    assert_eq!(unknown.output["retirement"], "pending");
    assert!(db.handoff_retirement_started(&b).unwrap());
    // A definitive read of non-archived state can clear preparation after an
    // uncertain reply, even when the retry supplies a stale revision.
    let (stale, ()) = tokio::join!(
        runtime.dispatch_project_handoff(
            ToolCall::ProjectHandoffWrite {
                project: id.clone(),
                session_id: "old".into(),
                request: serde_json::from_value(
                    json!({"action":"archive","task_id":"done","expected_revision":99})
                )
                .unwrap(),
            },
            Some(&auth)
        ),
        reply(&runtime, &root, false)
    );
    assert!(!stale.success);
    assert!(!db.handoff_retirement_started(&b).unwrap());
    let (result, ()) = tokio::join!(
        runtime.dispatch_project_handoff(
            ToolCall::ProjectHandoffWrite {
                project: id.clone(),
                session_id: "old".into(),
                request
            },
            Some(&auth)
        ),
        async {
            reply(&runtime, &root, false).await;
            reply(&runtime, &root, false).await;
        }
    );
    assert!(result.success, "{result:?}");
    assert_eq!(result.output["retirement"], "retired");
    assert!(db.handoff_retirement_started(&b).unwrap());
    assert!(runtime
        .handoff_admission(&resolved, Some("old"), Some(&auth))
        .await
        .is_err());
    let (read, ()) = tokio::join!(
        runtime.dispatch_project_handoff(
            ToolCall::ProjectHandoffRead {
                project: id,
                session_id: None,
                task_id: Some("done".into())
            },
            Some(&auth)
        ),
        reply(&runtime, &root, false)
    );
    assert!(read.success);
    assert_eq!(read.output["archived"], true);
    assert_eq!(read.output["event_count"], 1);
    assert_eq!(read.output["checkpoint"], checkpoint["checkpoint"]);
}
